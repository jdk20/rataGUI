import unicodedata
import re


def slugify(value, allow_unicode=False):
    """
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    # Remove all characters that are not word chars, whitespace, or hyphens
    value = re.sub(r"[^\w\s-]", "", value)
    # Collapse runs of whitespace and/or hyphens into a single hyphen
    return re.sub(r"[-\s]+", "-", value).strip("-_")


from PyQt6.QtCore import QRunnable, QObject, pyqtSlot, pyqtSignal


class ThreadSignals(QObject):
    """Qt signals emitted by WorkerThread to communicate results back to the main thread.

    :signal finished: Emitted when the worker function completes (success or failure).
    :signal error: Emitted with the exception if the worker function raises.
    :signal result: Emitted with the return value on success.
    """

    finished = pyqtSignal()
    error = pyqtSignal(Exception)
    result = pyqtSignal(object)


class WorkerThread(QRunnable):
    """
    Worker that runs an arbitrary function in QThreadPool.

    Emits finished, error and result pyqtSignals.

    :param callback: The function callback to run on this worker thread. Supplied args and
                     kwargs will be passed through to the runner.
    :type callback: function
    :param args: Arguments to pass to the callback function
    :param kwargs: Keywords to pass to the callback function
    """

    def __init__(self, func, *args, **kwargs):
        super().__init__()

        # Store constructor arguments (re-used for processing)
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = ThreadSignals()

    @pyqtSlot()
    def run(self):
        """
        Initialise the runner function with passed args, kwargs.
        """

        # Retrieve args/kwargs here; and fire processing using them
        try:
            result = self.func(*self.args, **self.kwargs)
        except Exception as err:
            self.signals.error.emit(err)
            raise err
        else:
            self.signals.result.emit(result)  # Return the result of the process
        finally:
            self.signals.finished.emit()  # Done
