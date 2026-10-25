"""Single worker with queued results; Tk callbacks run only in drain(), never workers."""
from concurrent.futures import ThreadPoolExecutor
import queue


class BackgroundTasks:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ledger-data')
        self.results = queue.Queue()
        self.closed = False
        self.pending = 0
        self.callbacks = {}
        self.next_ticket = 0

    def submit(self, work, success, failure):
        if self.closed:
            raise RuntimeError('Background worker is closed')
        self.pending += 1
        self.next_ticket += 1
        ticket = self.next_ticket
        self.callbacks[ticket] = (success, failure)
        future = self.executor.submit(work)
        def finished(future):
            try:
                result = future.result()
            except Exception as exc:
                self.results.put((ticket, False, exc))
            else:
                self.results.put((ticket, True, result))
        future.add_done_callback(finished)
        return future

    def drain(self):
        while True:
            try:
                ticket, success, value = self.results.get_nowait()
            except queue.Empty:
                break
            self.pending -= 1
            callbacks = self.callbacks.pop(ticket, None)
            if not self.closed and callbacks:
                callback = callbacks[0 if success else 1]
                callback(value)

    def close(self):
        self.closed = True
        self.callbacks.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)
