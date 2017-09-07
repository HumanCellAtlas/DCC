#!/usr/bin/env python
# coding: utf-8

from __future__ import absolute_import, division, print_function, unicode_literals

import itertools
import os
import sys
import time
import typing
import unittest

pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))  # noqa
sys.path.insert(0, pkg_root)  # noqa

from dss.events import chunkedtask
from dss.events.chunkedtask import aws
from dss.events.chunkedtask._awstest import AWS_FAST_TEST_CLIENT_NAME, AWSFastTestTask, is_task_complete
from tests.chunked_worker import TestStingyRuntime, run_task_to_completion


class TestChunkedTask(chunkedtask.Task[typing.Tuple[int, int, int], typing.Tuple[int, int]]):
    def __init__(
            self,
            state: typing.Tuple[int, int, int],
            expected_max_one_unit_runtime_millis: int) -> None:
        self.x0, self.x1, self.rounds_remaining = state
        self._expected_max_one_unit_runtime_millis = expected_max_one_unit_runtime_millis

    @property
    def expected_max_one_unit_runtime_millis(self) -> int:
        return self._expected_max_one_unit_runtime_millis

    def get_state(self) -> typing.Any:
        return self.x0, self.x1, self.rounds_remaining

    def run_one_unit(self) -> typing.Optional[typing.Tuple[int, int]]:
        x0new = self.x0 + self.x1
        self.x1 = self.x0
        self.x0 = x0new

        self.rounds_remaining -= 1

        if self.rounds_remaining == 0:
            return self.x0, self.x1
        return None


class TestChunkedTaskRunner(unittest.TestCase):
    def test_workload_resumes(self):
        initial_state = (1, 1, 25)
        expected_max_one_unit_runtime_millis = 10  # we know exactly how long we'll take.  we're so good at guessing!

        freeze_count, result = run_task_to_completion(
            TestChunkedTask,
            initial_state,
            lambda results: TestStingyRuntime(results, itertools.repeat(sys.maxsize, 19)),
            lambda task_class, task_state, runtime: task_class(task_state, expected_max_one_unit_runtime_millis),
            lambda runtime: runtime.result,
            lambda runtime: runtime.scheduled_work,
        )

        self.assertEqual(result, (196418, 121393))
        self.assertEqual(freeze_count, 2)


class TestAWSChunkedTask(unittest.TestCase):
    def test_fast(self):
        task_id = aws.schedule_task(AWSFastTestTask, [0, 5])

        starttime = time.time()
        while time.time() < starttime + 30:
            if is_task_complete(AWS_FAST_TEST_CLIENT_NAME, task_id):
                return

            time.sleep(1)

        self.fail("Did not find success marker in logs")


if __name__ == '__main__':
    unittest.main()
