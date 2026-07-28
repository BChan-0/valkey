# Intentional runtime exception for test-failure detector validation.
# A non-assertion Tcl error raised in a test body is re-raised past the
# test proc (see tests/support/test.tcl) and reaches test_client_main's
# catch, which reports it to the test server as an "exception" failure.
# This triggers the "exception" failure type in the JSON artifact.
#
# The exception handler kills all clients and ends the whole run, so schedule
# this file last, after the other dummy failure files.

start_server {tags {"dummy"}} {
    test "dummy-exception - intentional runtime exception" {
        error "Intentional runtime exception for detector testing"
    }
}
