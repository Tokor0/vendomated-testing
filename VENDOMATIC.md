# Vendomatic

A toy vending machine, written to be driven from the outside. Pure Python,
standard library only, `src/vendomatic/`.

The same machine is reachable four ways — as a Python object, as a JSON file on
disk, as a command line program, and as an HTTP API — and each way exposes a
little more of the world: files, processes, sockets, threads, time.

```console
$ export PYTHONPATH=$PWD/src          # `nix develop` does this for you
$ python -m vendomatic reset
$ python -m vendomatic insert 100 25 10
$ python -m vendomatic buy A1
Dispensed Salted Crisps (A1) for $1.25
Change: $0.10 (1 x $0.10)
```

## The domain

A machine is a grid of **slots**. A slot has a code (`A1`), a product, a price,
a quantity and a capacity. Customers put **coins** in — nickels, dimes,
quarters and dollar coins, `5 10 25 100` — building up **credit**, then select
a slot. The machine dispenses the item and returns the difference from its
**coin bank**, which is a finite pile of coins and can run out of the right
denominations.

Restocking, loading change and emptying the cash box live behind a four-digit
**service PIN**. The machine is locked until someone unlocks it, and locks
again afterwards.

All money is integer **cents**. `$1.25` is `125`, never `1.25`.

## Layers

| Module | What it adds |
| --- | --- |
| `vendomatic.money` | pure functions: parse and format prices, validate coins, make change |
| `vendomatic.inventory` | `Slot` and `Inventory` — stock levels, capacity, sold-out |
| `vendomatic.machine` | `VendingMachine` — credit, purchases, service mode, sales log |
| `vendomatic.storage` | JSON state files (atomic writes) and CSV sales exports |
| `vendomatic.cli` | the `vendomatic` program: one transaction per invocation, exit codes |
| `vendomatic.server` | JSON over HTTP, with a service-token header on `/admin` |
| `vendomatic.maintenance` | background jobs that take seconds, and a cabinet that cools slowly |
| `vendomatic.errors` | every deliberate failure, all deriving from `VendingError` |

## Python

```python
from vendomatic import VendingMachine, Inventory, demo_machine

machine = demo_machine()          # six slots, stocked, PIN 1234
machine.insert_coins(100, 25, 10) # -> 135, the new credit in cents
receipt = machine.select("A1")
receipt.item_name                 # 'Salted Crisps'
receipt.change                    # {10: 1}
machine.credit                    # '$0.00'

machine.unlock("1234")
machine.restock("C2", 3)
machine.lock()

machine.sales_report()
# {'items_sold': 1, 'revenue_cents': 125, 'revenue': '$1.25',
#  'by_item': {'Salted Crisps': {'count': 1, 'revenue_cents': 125}}}
```

Build your own instead of using the demo:

```python
inventory = Inventory()
inventory.add_slot("A1", "Salted Crisps", 125, quantity=5)
machine = VendingMachine(inventory, coin_bank={25: 4}, service_pin="1234")
```

`VendingMachine` takes a `clock` — any callable returning a `datetime` — which
it uses to timestamp sales, so the passage of time can be supplied rather than
waited for. `maintenance.CabinetThermometer` takes one too.

### What fails, and how

Every deliberate failure raises a subclass of `VendingError`:

| Exception | Raised when |
| --- | --- |
| `InvalidPriceError` | a price string will not parse, or is negative |
| `InvalidCoinError` | a coin is not one of `5 10 25 100` |
| `ExactChangeError` | the coin bank cannot make up the change owed |
| `InvalidSlotCodeError` | a slot code is not a letter plus a digit 1–9 |
| `SlotNotFoundError` | no slot has that code |
| `DuplicateSlotError` | that code is already in use |
| `CapacityExceededError` | a restock would overfill a slot |
| `SoldOutError` | the slot exists but is empty |
| `InsufficientCreditError` | the credit is below the price |
| `MachineLockedError` | a service operation was tried while locked, or the PIN was wrong |
| `StorageError` | a state file is missing, unreadable or corrupt |
| `JobNotFoundError` | no background job has that id |

Messages are stable and part of the behaviour — amounts in them are always
formatted like `$1.25`.

A purchase checks, in order: the slot exists, it is not sold out, the credit
covers the price, the change can be made. A purchase that fails at any step
changes nothing — no item moves, no coin moves, and the credit stays inserted.

## Command line

`vendomatic` (or `python -m vendomatic`). Each invocation reads a state file,
does one thing, and writes it back: the file *is* the machine.

| Command | Does |
| --- | --- |
| `reset [--empty] [--pin PIN]` | write a fresh state file — demo stock unless `--empty` |
| `status` | credit, stock, bank, takings, lock state |
| `slots` | list every slot |
| `slot CODE` | show one slot |
| `insert CENTS [CENTS …]` | insert coins |
| `buy CODE` | purchase |
| `refund` | return the inserted coins |
| `restock CODE QTY --pin PIN` | add stock |
| `collect --pin PIN` | empty the coin bank |
| `report [--csv PATH]` | sales summary, optionally exported |
| `serve [--host H] [--port P] [--token T]` | run the HTTP API |

`--state PATH` and `--json` work before or after the command name. With
`--json` every command prints one JSON object — errors included, on stderr.

The state file is `--state`, else `$VENDOMATIC_STATE`, else
`./vendomatic-state.json`. Every command but `reset` needs it to exist.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | the command succeeded |
| `1` | the machine refused — sold out, not enough credit, locked … |
| `2` | bad command line — unknown command, missing or wrong arguments |
| `3` | the state file is missing, unreadable or corrupt |

## HTTP

`vendomatic serve --port 8080 --token service-token`, or in-process:

```python
from vendomatic.server import create_server
server = create_server(port=0, token="service-token")   # port 0 picks a free one
server.port, server.url
```

Requests and responses are JSON.

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/health` | | `{"status": "ok", "slots": 6}` |
| `GET` | `/slots` | | every slot |
| `GET` | `/slots/{code}` | | one slot |
| `GET` | `/credit` | | credit and the coins held |
| `POST` | `/coins` | `{"value": 25}` | `201` and the new credit |
| `POST` | `/refund` | | what came back |
| `POST` | `/purchase` | `{"code": "A1"}` | the receipt |
| `GET` | `/sales` | | the report plus every sale |
| `POST` | `/admin/restock` | `{"code": "A1", "quantity": 3}` | the slot |
| `POST` | `/admin/collect` | | what was collected |
| `POST` | `/admin/jobs/restock` | `{"code": "A1", "quantity": 3, "delay": 2}` | `202` and a job id |
| `GET` | `/jobs/{id}` | | that job's status and result |

`/admin/*` requires the header `X-Service-Token`; without it, `401`.

Statuses: `200` fine, `201` coin accepted, `202` job queued, `400` malformed,
`401` bad token, `404` unknown path/slot/job, `405` wrong method, `409` the
machine refused. Error bodies are `{"error": "...", "type": "SoldOutError"}`.

Set `VENDOMATIC_HTTP_LOG=1` to get the usual request log on stderr.

## Things that take time

```python
from vendomatic.maintenance import JobRunner, CabinetThermometer

with JobRunner(default_delay=2.0) as runner:
    job_id = runner.schedule_restock(machine, "C2", 3, pin="1234")
    runner.get_status(job_id)      # 'pending' -> 'running' -> 'succeeded'
    runner.wait_for(job_id, timeout=10).result
```

`submit` returns immediately; the work happens on a background thread after a
delay. A job ends `succeeded`, `failed` (with the reason in `job.error`) or
`cancelled` — `cancel` only works while it is still pending.

`CabinetThermometer` cools from 21 °C towards 4 °C at 2 °C per second, computed
fresh on every `read()`. It has no thread of its own: the answer depends on
when you ask.
