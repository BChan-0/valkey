# Intentional memory leak for test-failure detector validation.
# This suite only surfaces errors under valgrind (--leak-check=full) or
# AddressSanitizer builds. Under normal runs the test passes.
#
# The DEBUG LEAK command sdsdup()s its argument and drops the pointer,
# producing a "definitely lost" report that valgrind/ASan will detect at
# server teardown. This triggers the "valgrind" or "sanitizer" failure type.

start_server {tags {"dummy"}} {
    test "dummy-memory - intentional leak via DEBUG leak" {
        r debug leak "intentional-leak-for-detector-testing"
        assert_equal [r ping] "PONG"
    }
}
