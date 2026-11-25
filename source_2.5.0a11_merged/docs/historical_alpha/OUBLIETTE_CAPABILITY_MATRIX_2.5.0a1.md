# Oubliette Capability Matrix — 2.5.0a5

| Mode | Static inspection | Protective request | Wallet custody crossing | Execution | Core dependency |
|---|---:|---:|---:|---:|---:|
| disabled | No | No | No | No | No |
| inspect | Yes | Yes | No | No | No |
| transaction | Yes | Yes | Yes, through Wallet | No | No |

The active Oubliette adapter records source=`oubliette`, channel=`OUB`, bounded coverage, and static findings. It refuses to claim custody change or Human Intent. Wallet records authoritative custody results separately.
