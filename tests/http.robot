*** Settings ***
Documentation    HTTP API tests for Vendomatic.

Resource         ../resources/http.resource

Test Setup       Start New Server
Test Teardown    Stop Server
Test Timeout     30 seconds


*** Test Cases ***
Health Reports OK
    [Documentation]    Check that the server is healthy.
    Server Should Be Healthy

Can Insert Coins
    [Documentation]    Attempts to insert valid coins. Verifies the resulting credit.
    FOR    ${coin}    IN    @{VALID_COINS}
        # TODO: Add credit verification logic
        Insert Coin    ${coin}
    END


Purchase With Insufficient Credit Should Be Denied
    [Documentation]    Attempts to purchase items with insufficient credit. Expects 409 response.
    Purchase    A1    409
    Insert Coin    ${100}
    Purchase    A1    409
