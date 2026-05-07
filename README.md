# ahoy

A terminal UI (curses) for managing [sshuttle](https://github.com/sshuttle/sshuttle) VPN tunnel connections. Navigate, toggle, and monitor multiple SSH-based tunnels from a single interactive screen.

```
┌ Toggle Menu ─────────────────────────────────────────┐
│ Label                Desired  Actual   Sync           │
│ mylab               [ ON ]   [ ON ]    ✓              │
│ office              [OFF ]   [OFF ]    ✓              │
└──────────────────────────────────────────────────────┘
┌ Info ────────────────────────────────────────────────┐
│ Connect to mylab                                      │
└──────────────────────────────────────────────────────┘
```

## Installation

### Homebrew (recommended)

```bash
brew tap galmasi/ahoy
brew install ahoy
```

Then set up your config:

```bash
mkdir -p ~/.config/ahoy
cp $(brew --prefix)/share/ahoy/config.example.json ~/.config/ahoy/config.json
$EDITOR ~/.config/ahoy/config.json
```

### Manual

```bash
git clone https://github.com/galmasi/ahoy.git
cd ahoy
pip install sshuttle
cp config.example.json ~/.config/ahoy/config.json
$EDITOR ~/.config/ahoy/config.json
python3 ahoy.py
```

## Configuration

ahoy looks for its config at `~/.config/ahoy/config.json`. Copy `config.example.json` as a starting point:

```json
{
  "sshkey": "~/.ssh/id_rsa",
  "sshoptions": "-oStrictHostKeyChecking=no -oBatchMode=yes -oPasswordAuthentication=no -oConnectTimeout=20",
  "sshuttlecmd": "sshuttle --disable-ipv6 --dns --python python3",
  "networks": {
    "mylab": {
      "jumphost": "user@jumphost.example.com",
      "gateway": "10.0.0.1",
      "nets": [ "10.0.0.0/16" ]
    }
  }
}
```

| Field | Description |
|---|---|
| `sshkey` | Path to the SSH private key used by sshuttle |
| `sshoptions` | Extra SSH options passed via sshuttle's `-e` flag |
| `sshuttlecmd` | Full path/invocation of the `sshuttle` binary |
| `networks` | Map of named tunnels, each with a jumphost, gateway IP, and list of CIDRs to route |

## Usage

```
ahoy
```

| Key | Action |
|---|---|
| `↑` / `k` | Move up |
| `↓` / `j` | Move down |
| `Space` / `Enter` | Toggle desired state |
| `q` / `Q` | Quit |

The **Desired** column reflects what you want; **Actual** reflects reality. The background thread reconciles them automatically every second.

## Requirements

- macOS or Linux
- Python 3.9+
- [sshuttle](https://github.com/sshuttle/sshuttle)

## License

MIT
