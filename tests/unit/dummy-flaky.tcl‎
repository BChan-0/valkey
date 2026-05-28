start_server {tags {"dummy"}} {
    test "dummy-flaky - basic SET and GET" {
        r SET mykey myvalue
        assert_equal [r GET mykey] "myvalue"
    }

    test "dummy-flaky - intentional failure" {
        r SET mykey myvalue
        assert_equal [r GET mykey] "wrongvalue"
    }

    test "dummy-flaky - another passing test" {
        r SET counter 0
        r INCR counter
        assert_equal [r GET counter] "1"
    }
}
