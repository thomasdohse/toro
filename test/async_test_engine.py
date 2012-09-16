import functools
import os
import time
import traceback
import types
import sys

from tornado import gen, ioloop


class PuritanicalIOLoop(ioloop.IOLoop):
    """
    A loop that quits when it encounters an Exception.
    """
    def handle_callback_exception(self, callback):
        exc_type, exc_value, tb = sys.exc_info()
        traceback.print_tb(tb, file=sys.stderr)
        raise exc_value


def async_test_engine(timeout_sec=5):
    if not isinstance(timeout_sec, int) and not isinstance(timeout_sec, float):
        raise TypeError(
"""Expected int or float, got %s
Use async_test_engine like:
    @async_test_engine()
or:
    @async_test_engine(timeout_sec=10)""" % (
        repr(timeout_sec)))

    timeout_sec = max(timeout_sec, float(os.environ.get('TIMEOUT_SEC', 0)))

    def decorator(func):
        class AsyncTestRunner(gen.Runner):
            def __init__(self, gen, timeout):
                # Tornado 2.3 added a second argument to Runner()
                super(AsyncTestRunner, self).__init__(gen, lambda: None)
                self.timeout = timeout

            def run(self):
                loop = ioloop.IOLoop.instance()
                assert isinstance(loop, PuritanicalIOLoop)

                try:
                    super(AsyncTestRunner, self).run()
                except Exception:
                    loop.remove_timeout(self.timeout)
                    loop.stop()
                    raise

                if self.finished:
                    loop.remove_timeout(self.timeout)
                    loop.stop()

        @functools.wraps(func)
        def _async_test(self):
            # Uninstall previous loop
            if hasattr(ioloop.IOLoop, '_instance'):
                del ioloop.IOLoop._instance

            loop = PuritanicalIOLoop()
            loop.install()

            def on_timeout():
                loop.stop()
                raise AssertionError("%s timed out" % func)

            timeout = loop.add_timeout(time.time() + timeout_sec, on_timeout)

            gen = func(self)
            assert isinstance(gen, types.GeneratorType), (
                "%s should be a generator, include a yield "
                "statement" % func
            )

            runner = AsyncTestRunner(gen, timeout)
            runner.run()
            loop.start()
            if not runner.finished:
                # Something stopped the loop before func could finish or throw
                # an exception.
                raise Exception('%s did not finish' % func)

        return _async_test
    return decorator

async_test_engine.__test__ = False # Nose otherwise mistakes it for a test


class AssertRaises(gen.Task):
    def __init__(self, exc_type, func, *args, **kwargs):
        super(AssertRaises, self).__init__(func, *args, **kwargs)
        if not isinstance(exc_type, type):
            raise TypeError("%s is not a class" % repr(exc_type))

        if not issubclass(exc_type, Exception):
            raise TypeError(
                "%s is not a subclass of Exception" % repr(exc_type))
        self.exc_type = exc_type

    def get_result(self):
        (result, error), _ = self.runner.pop_result(self.key)
        if not isinstance(error, self.exc_type):
            if error:
                raise AssertionError("%s raised instead of %s" % (
                    repr(error), self.exc_type.__name__))
            else:
                raise AssertionError("%s not raised" % self.exc_type.__name__)
        return result


class AssertEqual(gen.Task):
    def __init__(self, expected, func, *args, **kwargs):
        super(AssertEqual, self).__init__(func, *args, **kwargs)
        self.expected = expected

    def get_result(self):
        (result, error), _ = self.runner.pop_result(self.key)
        if error:
            raise error


        if self.expected != result:
            raise AssertionError("%s returned %s\nnot\n%s" % (
                self.func, repr(result), repr(self.expected)))

        return result