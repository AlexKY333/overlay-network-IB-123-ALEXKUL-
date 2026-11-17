import asyncio
from config import REPUBLISH_INTERVAL
from republisher import DHTRepublisher


class DHTRepublishService:
    def __init__(
        self,
        republisher: DHTRepublisher,
        interval: float = REPUBLISH_INTERVAL,
    ):
        if interval <= 0:
            raise ValueError(
                "Republish interval must be greater than 0"
            )

        self.republisher = republisher
        self.interval = interval

        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def run_once(self) -> int:
        """
        Performs one republish check.

        Returns the number of refreshed records.
        """

        refreshed = (
            self.republisher.republish_due_records()
        )

        return len(refreshed)

    async def _run(self):
        self._running = True

        try:
            while True:
                await self.run_once()

                await asyncio.sleep(
                    self.interval
                )

        except asyncio.CancelledError:
            raise

        finally:
            self._running = False

    def start(self) -> None:
        """
        Starts the background republish task.
        """

        if self._task is not None:
            if not self._task.done():
                return

        self._task = asyncio.create_task(
            self._run()
        )

    async def stop(self) -> None:
        """
        Stops the background republish task.
        """

        if self._task is None:
            return

        if self._task.done():
            self._task = None
            self._running = False
            return

        self._task.cancel()

        try:
            await self._task
        except asyncio.CancelledError:
            pass

        self._task = None
        self._running = False