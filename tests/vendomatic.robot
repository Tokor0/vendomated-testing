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
    [Documentation]    Attempts to unlock the machine with invalid PINs and a valid but wrong PIN.
    ...                The machine should remain locked.
    FOR    ${pin}    IN    @{INVALID_PINS}    ${ALT_PIN}
        Unlock Should Be Denied On Wrong PIN    ${pin}
    END
    Machine Should Be Locked

Service PIN Can Be Changed
    [Documentation]    Attempts to change the PIN and validates the change takes effect.
    Set Service Pin    ${SERVICE_PIN}    ${ALT_PIN}
    Unlock Should Be Denied On Wrong PIN    ${SERVICE_PIN}
    Machine Should Be Locked
    Unlock Machine    ${ALT_PIN}
    Machine Should Be Unlocked

Service PIN Change Denied On Invalid New PIN
    [Documentation]    Attempts to change PIN to an invalid PIN. This is expected to be denied.
    FOR    ${pin}    IN    @{INVALID_PINS}
        Invalid Value Should Be Denied    Set Service Pin    ${SERVICE_PIN}    ${pin}
    END

Service PIN Change Denied On Wrong Or Invalid Current PIN
    [Documentation]    Attempts to change PIN using wrong or invalid current PINs.
    ...                This is expected to be denied.
    FOR    ${pin}    IN    @{INVALID_PINS}    ${ALT_PIN}
        Service Operation Should Be Denied    Set Service Pin    ${pin}    ${ALT_PIN}
    END

Service Mode Actions Cannot Be Executed When Locked
    [Documentation]    Service mode actions should not be allowed when the machine is locked.
    [Template]    Service Operation Should Be Denied
    Add Slot    A1    product    100
    Clear Sales
    Collect Cash
    Load Coins    {100: 1}
    Restock    A1
