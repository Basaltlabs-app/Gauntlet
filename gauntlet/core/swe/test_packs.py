"""Built-in SWE test packs -- real bugs with real test suites.

Each test case contains:
  - Buggy source code
  - A bug report (what the model sees)
  - A test suite (what verifies the fix)
  - The correct fix (for reference scoring)

These run inside Docker containers with pytest.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TestCase:
    """A single SWE-bench style test case."""
    name: str
    category: str
    filename: str
    issue: str              # bug report the model sees
    buggy_code: str         # the broken code
    test_code: str          # pytest test suite that validates the fix
    solution_code: str      # correct fix (for reference)
    expected_tests: int     # how many tests should pass
    docker_image: str = "gauntlet-swe-python"
    test_command: str = "python -m pytest /workspace/test_fix.py -v --tb=short"
    timeout: int = 30


@dataclass
class TestPack:
    """A collection of related test cases."""
    name: str
    description: str
    language: str
    cases: list[TestCase] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
# Python Bug Fixes
# ══════════════════════════════════════════════════════════════════════

PYTHON_BUGS = TestPack(
    name="python-bugs",
    description="Real Python bugs: off-by-one errors, logic flaws, edge cases",
    language="python",
    cases=[
        TestCase(
            name="Binary Search Off-by-One",
            category="bug_fix",
            filename="search.py",
            issue=(
                "binary_search returns -1 for elements that exist in the list. "
                "For example, binary_search([1, 3, 5, 7, 9], 7) returns -1 "
                "instead of 3. The function enters an infinite loop for some inputs."
            ),
            buggy_code="""\
def binary_search(arr, target):
    low, high = 0, len(arr)
    while low < high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid
        else:
            high = mid
    return -1
""",
            test_code="""\
from fix import binary_search

def test_find_existing():
    assert binary_search([1, 3, 5, 7, 9], 7) == 3

def test_find_first():
    assert binary_search([1, 3, 5, 7, 9], 1) == 0

def test_find_last():
    assert binary_search([1, 3, 5, 7, 9], 9) == 4

def test_not_found():
    assert binary_search([1, 3, 5, 7, 9], 4) == -1

def test_empty():
    assert binary_search([], 1) == -1

def test_single_element_found():
    assert binary_search([5], 5) == 0

def test_single_element_not_found():
    assert binary_search([5], 3) == -1
""",
            solution_code="""\
def binary_search(arr, target):
    low, high = 0, len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
""",
            expected_tests=7,
        ),

        TestCase(
            name="LRU Cache Eviction Bug",
            category="bug_fix",
            filename="cache.py",
            issue=(
                "The LRU cache does not evict the least recently used item when full. "
                "After inserting 3 items into a cache with capacity 2, all 3 items "
                "remain. The cache should only hold the 2 most recently accessed items."
            ),
            buggy_code="""\
class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.cache = {}
        self.order = []

    def get(self, key):
        if key in self.cache:
            return self.cache[key]
        return -1

    def put(self, key, value):
        if key in self.cache:
            self.cache[key] = value
        else:
            self.cache[key] = value
            self.order.append(key)
""",
            test_code="""\
from fix import LRUCache

def test_basic_put_get():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    assert c.get("b") == 2

def test_eviction():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)  # should evict "a"
    assert c.get("a") == -1
    assert c.get("c") == 3

def test_access_refreshes():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")      # refresh "a"
    c.put("c", 3)   # should evict "b" not "a"
    assert c.get("a") == 1
    assert c.get("b") == -1

def test_update_existing():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("a", 10)
    assert c.get("a") == 10

def test_capacity_one():
    c = LRUCache(1)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == -1
    assert c.get("b") == 2
""",
            solution_code="""\
from collections import OrderedDict

class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.cache = OrderedDict()

    def get(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return -1

    def put(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
""",
            expected_tests=5,
        ),

        TestCase(
            name="Flatten Nested List Bug",
            category="bug_fix",
            filename="flatten.py",
            issue=(
                "flatten([[1, [2, 3]], [4, [5, [6]]]]) returns [1, [2, 3], 4, [5, [6]]] "
                "instead of [1, 2, 3, 4, 5, 6]. It only flattens one level deep "
                "instead of recursively flattening all nested lists."
            ),
            buggy_code="""\
def flatten(lst):
    result = []
    for item in lst:
        if isinstance(item, list):
            result.extend(item)
        else:
            result.append(item)
    return result
""",
            test_code="""\
from fix import flatten

def test_already_flat():
    assert flatten([1, 2, 3]) == [1, 2, 3]

def test_one_level():
    assert flatten([[1, 2], [3, 4]]) == [1, 2, 3, 4]

def test_deep_nested():
    assert flatten([[1, [2, 3]], [4, [5, [6]]]]) == [1, 2, 3, 4, 5, 6]

def test_empty():
    assert flatten([]) == []

def test_mixed():
    assert flatten([1, [2, [3]], 4]) == [1, 2, 3, 4]

def test_all_nested():
    assert flatten([[[1]], [[2]], [[3]]]) == [1, 2, 3]
""",
            solution_code="""\
def flatten(lst):
    result = []
    for item in lst:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result
""",
            expected_tests=6,
        ),

        TestCase(
            name="Rate Limiter Time Window",
            category="implementation",
            filename="rate_limiter.py",
            issue=(
                "Implement a rate limiter. The current implementation counts all calls "
                "ever made instead of using a sliding time window. After max_calls "
                "have been made, it blocks forever instead of allowing calls once "
                "the window has passed."
            ),
            buggy_code="""\
import time

class RateLimiter:
    def __init__(self, max_calls, period_seconds):
        self.max_calls = max_calls
        self.period = period_seconds
        self.call_count = 0

    def allow(self):
        if self.call_count < self.max_calls:
            self.call_count += 1
            return True
        return False
""",
            test_code="""\
import time
from fix import RateLimiter

def test_allows_under_limit():
    rl = RateLimiter(3, 1.0)
    assert rl.allow() == True
    assert rl.allow() == True
    assert rl.allow() == True

def test_blocks_over_limit():
    rl = RateLimiter(2, 1.0)
    assert rl.allow() == True
    assert rl.allow() == True
    assert rl.allow() == False

def test_allows_after_window():
    rl = RateLimiter(1, 0.1)
    assert rl.allow() == True
    assert rl.allow() == False
    time.sleep(0.15)
    assert rl.allow() == True

def test_sliding_window():
    rl = RateLimiter(2, 0.2)
    assert rl.allow() == True
    time.sleep(0.1)
    assert rl.allow() == True
    assert rl.allow() == False
    time.sleep(0.15)
    assert rl.allow() == True
""",
            solution_code="""\
import time

class RateLimiter:
    def __init__(self, max_calls, period_seconds):
        self.max_calls = max_calls
        self.period = period_seconds
        self.calls = []

    def allow(self):
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.period]
        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True
        return False
""",
            expected_tests=4,
        ),

        TestCase(
            name="Linked List Cycle Detection",
            category="implementation",
            filename="linked_list.py",
            issue=(
                "Implement Floyd's cycle detection for a linked list. "
                "The current has_cycle function uses a set to track visited nodes, "
                "which works but uses O(n) memory. Rewrite it to use O(1) memory "
                "with the tortoise and hare algorithm."
            ),
            buggy_code="""\
class Node:
    def __init__(self, val, next=None):
        self.val = val
        self.next = next

def has_cycle(head):
    visited = set()
    current = head
    while current:
        if id(current) in visited:
            return True
        visited.add(id(current))
        current = current.next
    return False
""",
            test_code="""\
from fix import Node, has_cycle

def test_no_cycle():
    head = Node(1, Node(2, Node(3)))
    assert has_cycle(head) == False

def test_with_cycle():
    a = Node(1)
    b = Node(2)
    c = Node(3)
    a.next = b
    b.next = c
    c.next = a
    assert has_cycle(a) == True

def test_empty():
    assert has_cycle(None) == False

def test_single_no_cycle():
    assert has_cycle(Node(1)) == False

def test_single_self_cycle():
    a = Node(1)
    a.next = a
    assert has_cycle(a) == True

def test_uses_constant_memory():
    # The function should NOT use a set/dict
    import inspect
    source = inspect.getsource(has_cycle)
    assert 'set()' not in source, "Should use O(1) memory, not a set"
    assert 'dict()' not in source, "Should use O(1) memory, not a dict"
    assert '{}' not in source, "Should use O(1) memory"
""",
            solution_code="""\
class Node:
    def __init__(self, val, next=None):
        self.val = val
        self.next = next

def has_cycle(head):
    slow = head
    fast = head
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
        if slow is fast:
            return True
    return False
""",
            expected_tests=6,
        ),
    ],
)


# ══════════════════════════════════════════════════════════════════════
# Algorithm Challenges
# ══════════════════════════════════════════════════════════════════════

ALGORITHMS = TestPack(
    name="algorithms",
    description="Classic algorithm problems with edge cases",
    language="python",
    cases=[
        TestCase(
            name="Two Sum",
            category="algorithms",
            filename="two_sum.py",
            issue=(
                "Implement two_sum(nums, target) that returns indices of two numbers "
                "that add up to target. Must run in O(n) time, not O(n^2). "
                "The current brute force solution is too slow for large inputs."
            ),
            buggy_code="""\
def two_sum(nums, target):
    for i in range(len(nums)):
        for j in range(len(nums)):
            if i != j and nums[i] + nums[j] == target:
                return [i, j]
    return []
""",
            test_code="""\
from fix import two_sum

def test_basic():
    result = two_sum([2, 7, 11, 15], 9)
    assert sorted(result) == [0, 1]

def test_middle():
    result = two_sum([3, 2, 4], 6)
    assert sorted(result) == [1, 2]

def test_negative():
    result = two_sum([-1, -2, -3, -4, -5], -8)
    assert sorted(result) == [2, 4]

def test_not_found():
    assert two_sum([1, 2, 3], 100) == []

def test_uses_hash_map():
    import inspect
    source = inspect.getsource(two_sum)
    has_dict = 'dict' in source or '{}' in source or 'hash' in source.lower()
    no_nested_loop = source.count('for ') <= 1
    assert has_dict or no_nested_loop, "Should use O(n) approach with hash map"
""",
            solution_code="""\
def two_sum(nums, target):
    seen = {}
    for i, num in enumerate(nums):
        complement = target - num
        if complement in seen:
            return [seen[complement], i]
        seen[num] = i
    return []
""",
            expected_tests=5,
        ),

        TestCase(
            name="Merge Intervals",
            category="algorithms",
            filename="intervals.py",
            issue=(
                "merge_intervals([[1,3],[2,6],[8,10],[15,18]]) should return "
                "[[1,6],[8,10],[15,18]] but currently returns the input unchanged. "
                "The function doesn't actually merge overlapping intervals."
            ),
            buggy_code="""\
def merge_intervals(intervals):
    if not intervals:
        return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for i in range(1, len(intervals)):
        merged.append(intervals[i])
    return merged
""",
            test_code="""\
from fix import merge_intervals

def test_overlapping():
    assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]

def test_no_overlap():
    assert merge_intervals([[1,2],[3,4],[5,6]]) == [[1,2],[3,4],[5,6]]

def test_all_overlap():
    assert merge_intervals([[1,4],[2,3]]) == [[1,4]]

def test_empty():
    assert merge_intervals([]) == []

def test_single():
    assert merge_intervals([[1,5]]) == [[1,5]]

def test_touching():
    assert merge_intervals([[1,2],[2,3]]) == [[1,3]]
""",
            solution_code="""\
def merge_intervals(intervals):
    if not intervals:
        return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
""",
            expected_tests=6,
        ),
    ],
)


# ══════════════════════════════════════════════════════════════════════
# All built-in packs
# ══════════════════════════════════════════════════════════════════════

BUILT_IN_PACKS = [PYTHON_BUGS, ALGORITHMS]

# Total test count
TOTAL_SWE_TESTS = sum(len(p.cases) for p in BUILT_IN_PACKS)
