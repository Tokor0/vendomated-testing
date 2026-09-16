*** Settings ***
Documentation    Tests for the Vendomatic toy Python library.
...              This is for the purpose of studying Robot Framework.

Library          vendomatic.machine.VendingMachine    service_pin=1234


*** Test Cases ***
Machine Starts Empty And Locked
    ${s} =    Status
    # Log To Console   \nSTATUS: ${s}
    Should Be Equal As Integers    ${s}[slots]    0
    Should Be True    ${s}[locked]

Machine Can Be Unlocked With PIN And Locked
    Unlock    1234
    ${s} =    Status
    # Log To Console   \nSTATUS: ${s}
    Should Be True    not ${s}[locked]
    Lock
    ${s} =    Status
    Should Be True    ${s}[locked]

Machine Not Unlocked By Wrong PIN
    Run Keyword And Expect Error    *Incorrect service PIN    Unlock    4321
    ${s} =    Status
    # Log To Console   \nSTATUS: ${s}
    Should Be True    ${s}[locked]

Service Mode Actions Cannot Be Executed When Locked
    Run Keyword And Expect Error    MachineLockedError*    Add Slot    "A1"    "product"    100
    Run Keyword And Expect Error    MachineLockedError*    Clear Sales
    Run Keyword And Expect Error    MachineLockedError*    Collect Cash
    Run Keyword And Expect Error    MachineLockedError*    Load Coins    {100: 1}
    Run Keyword And Expect Error    MachineLockedError*    Restock    "A1"


