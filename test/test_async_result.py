"""
Test toro.AsyncResult.
"""

from __future__ import with_statement

from functools import partial
import time
import unittest

from tornado import gen, stack_context
from tornado.ioloop import IOLoop

import toro

from test import make_callback
from test.async_test_engine import async_test_engine


class TestAsyncResult(unittest.TestCase):
    def test_str(self):
        result = toro.AsyncResult()
        str(result)
        result.set('fizzle')
        self.assertTrue('fizzle' in str(result))
        self.assertFalse('waiters' in str(result))

        result = toro.AsyncResult()
        result.get(lambda: None)
        self.assertTrue('waiters' in str(result))

    def test_get_nowait(self):
        # Without a callback, get() is non-blocking. 'timeout' is ignored.
        self.assertRaises(toro.NotReady, toro.AsyncResult().get)
        self.assertRaises(toro.NotReady, toro.AsyncResult().get, timeout=1)

    @async_test_engine()
    def test_returns_none_after_timeout(self, done):
        start = time.time()
        value = yield gen.Task(toro.AsyncResult().get, timeout=.01)
        duration = time.time() - start
        self.assertAlmostEqual(.01, duration, places=2)
        self.assertEqual(value, None)
        done()

    @async_test_engine()
    def test_set(self, done):
        result = toro.AsyncResult()
        self.assertFalse(result.ready())
        IOLoop.instance().add_timeout(
            time.time() + .01, partial(result.set, 'hello'))
        start = time.time()
        value = yield gen.Task(result.get)
        duration = time.time() - start
        self.assertAlmostEqual(.01, duration, places=2)
        self.assertTrue(result.ready())
        self.assertEqual('hello', value)

        # Second and third get()'s work too
        self.assertEqual('hello', (yield gen.Task(result.get)))
        self.assertEqual('hello', (yield gen.Task(result.get)))

        # Non-blocking get() works
        self.assertEqual('hello', result.get())

        # Timeout ignored now
        start = time.time()
        value = yield gen.Task(result.get)
        duration = time.time() - start
        self.assertAlmostEqual(0, duration, places=2)
        self.assertEqual('hello', value)

        # set() only allowed once
        self.assertRaises(toro.AlreadySet, result.set, 'whatever')
        done()

    @async_test_engine()
    def test_set_callback(self, done):
        # Test that a callback passed to set() runs after callbacks registered
        # with get()
        result = toro.AsyncResult()
        history = []
        result.get(make_callback('get1', history))
        result.get(make_callback('get2', history))
        result.set('foo', make_callback('set', history))
        yield gen.Task(IOLoop.instance().add_callback)
        self.assertEqual(['get1', 'get2', 'set'], history)
        done()

    @async_test_engine()
    def test_get_timeout(self, done):
        result = toro.AsyncResult()
        start = time.time()
        value = yield gen.Task(result.get, timeout=.01)
        duration = time.time() - start
        self.assertAlmostEqual(.01, duration, places=2)
        self.assertEqual(None, value)
        self.assertFalse(result.ready())

        # Timed-out waiter doesn't cause error
        result.set('foo')
        self.assertTrue(result.ready())
        start = time.time()
        value = yield gen.Task(result.get, timeout=.01)
        duration = time.time() - start
        self.assertEqual('foo', value)
        self.assertAlmostEqual(0, duration, places=2)
        done()

    # TODO: similar for all toro classes
    def test_exc(self):
        # Test that raising an exception from a get() callback doesn't
        # propagate up to set()'s caller, and that StackContexts are correctly
        # managed
        result = toro.AsyncResult()
        loop = IOLoop.instance()
        loop.add_timeout(time.time() + .02, loop.stop)

        # Absent Python 3's nonlocal keyword, we need some place to store
        # results from inner functions
        outcomes = {
            'value': None,
            'set_result_exc': None,
            'get_result_exc': None,
        }

        def set_result():
            try:
                result.set('hello')
            except Exception, e:
                outcomes['set_result_exc'] = e

        def callback(value):
            outcomes['value'] = value
            assert False

        def catch_get_result_exception(type, value, traceback):
            outcomes['get_result_exc'] = type

        with stack_context.ExceptionStackContext(catch_get_result_exception):
            result.get(callback)

        loop.add_timeout(time.time() + .01, set_result)
        loop.start()
        self.assertEqual(outcomes['value'], 'hello')
        self.assertEqual(outcomes['get_result_exc'], AssertionError)
        self.assertEqual(outcomes['set_result_exc'], None)

    def test_io_loop(self):
        global_loop = IOLoop.instance()
        custom_loop = IOLoop()
        self.assertNotEqual(global_loop, custom_loop)
        result = toro.AsyncResult(custom_loop)

        def callback(value):
            assert value == 'foo'
            custom_loop.stop()

        result.get(callback)
        result.set('foo')
        custom_loop.start()