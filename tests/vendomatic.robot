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

    # Check that the pin can also be changed



Machine Not Unlocked By Wrong PIN
    # Probably the weakest possible way to test this BTW, but it will suffice for this
    Run Keyword And Expect Error    *Incorrect service PIN    Unlock    4321
    ${s} =    Status
    # Log To Console   \nSTATUS: ${s}
    Should Be True    ${s}[locked]
    Run Keyword And Expect Error    MachineLockedError*    Set Service Pin    4321    3214



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
    Run Keyword And Expect Error    MachineLockedError*    Add Slot    "A1"    "product"    100
    Run Keyword And Expect Error    MachineLockedError*    Clear Sales
    Run Keyword And Expect Error    MachineLockedError*    Collect Cash
    Run Keyword And Expect Error    MachineLockedError*    Load Coins    {100: 1}
    Run Keyword And Expect Error    MachineLockedError*    Restock    "A1"



