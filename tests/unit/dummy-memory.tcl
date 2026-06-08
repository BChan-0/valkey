start_server {tags {"dummy"}} {
    # NOTE: This suite only surfaces a memory error when the server is run
    # under valgrind (./runtest --valgrind) or a sanitizer build
    # (make SANITIZER=address ...). Under a normal ./runtest the leak below
    # happens but nothing inspects for it, so the test just passes.
    test "dummy-memory - intentional leak via DEBUG leak" {
        # DEBUG leak sdsdup()s its argument and drops the pointer, so the
        # duplicated string is never freed. At server teardown this shows up
        # as a "definitely lost" report under valgrind --leak-check=full, or
        # a leak report under AddressSanitizer. It is a real memory error,
        # not a faked Tcl assertion, so it exercises check_valgrind_errors /
        # check_sanitizer_errors the way a genuine bug would.
        r debug leak "intentional-leak-for-detector-testing"
        assert_equal [r ping] "PONG"
    }
}
