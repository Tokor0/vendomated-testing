*** Settings ***
Documentation    Tests for the Vendomatic toy Python library.
...              This is for the purpose of studying Robot Framework.

Resource         ../resources/vendomatic.resource


*** Test Cases ***
Machine Starts Empty And Locked
    [Documentation]    A new vending machine instance should be empty and locked.
    Machine Should Have N Slots    0
    Machine Should Be Locked

Machine Can Be Unlocked With PIN And Then Locked
    [Documentation]    Unlock the machine and validate effect.
    ...                Then lock and validate effect.
    Unlock Machine
    Machine Should Be Unlocked
    Lock
    Machine Should Be Locked

Machine Not Unlocked By Wrong Or Invalid PIN
    [Documentation]    Attempt to unlock the machine with invalid PINs and a valid but wrong PIN.
    ...                The machine should remain locked.
    FOR    ${pin}    IN    @{INVALID_PINS}    ${ALT_PIN}
        # Log To Console    TESTING PIN: ${pin}
        Run Keyword And Expect Error    *Incorrect service PIN    Unlock Machine    ${pin}
    END
    Machine Should Be Locked

Set Service Pin Behavior
    # Wrong but valid current PIN
    Run Keyword And Expect Error    MachineLockedError*    Set Service Pin    4321    3214

    # New PINs of wrong length, and a bit of probabilistic testing
    #
    # This kinda sucks actually, assuming the goal is to uniformly sample the length of
    # PIN, as it heavily biases longer PINS by having vastly more of them in the sample space.
    #
    # Anyway, it's a for-loop, which is nice.
    ${pins} =    Evaluate    random.sample(range(1000), 5) + random.sample(range(10000, sys.maxsize), 10)
    FOR    ${pin}    IN    @{pins}
        Log To Console    TESTING PIN: ${pin}
        Run Keyword And Expect Error    MachineLockedError*    Set Service Pin    4321    ${pin}
        Run Keyword And Expect Error    ValueError*    Set Service Pin    1234    ${pin}
    END

    # Valid call
    Set Service Pin    1234    4321
    Run Keyword And Expect Error    MachineLockedError*    Set Service Pin    1234    3214
    Unlock    4321
    ${s} =    Status
    Should Be True    not ${s}[locked]

Service Mode Actions Cannot Be Executed When Locked
    [Documentation]    Service mode actions should not be allowed when the machine is locked.
    [Template]    Service Operation Should Be Denied
    Add Slot    "A1"    "product"    100
    Clear Sales
    Collect Cash
    Load Coins    {100: 1}
    Restock    "A1"
