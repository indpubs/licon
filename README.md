# licon — Lighting Control

A simple interface to DALI lighting, using
[python-dali](https://github.com/sde1000/python-dali).

Generates plain text reports from the command line, or emails HTML
formatted reports.

Can issue some basic lighting control commands (DAPC etc.)  from the
command line, targetted at a single device, a group, a whole DALI bus
or a whole site.

Currently assumes the DALI bus is connected via
[daliserver](https://github.com/onitake/daliserver), but should be
simple to adapt to other interfaces if necessary.

Configuration is in [TOML](https://toml.io/). An abbreviated example:

```
[haymakers]

name = "Haymakers"
email-to = [
    "sde@individualpubs.co.uk",
    ]
email-from = "Lighting Status <sde@individualpubs.co.uk>"

[haymakers.buses]

main.hostname = "icarus.haymakers.i.individualpubs.co.uk"
main.port = 55825

[[haymakers.gear]]
bus = "main"
address = 46
name = "Garden corridor"

[[haymakers.gear]]
bus = "main"
address = 12
name = "Spirits store"

[[haymakers.gear]]
bus = "main"
address = 26
name = "Cellar back corner"

[[haymakers.gear]]
bus = "main"
address = 27
name = "Cellar entrance"
related-emergency = 11
```

## Installation

First ensure [poetry](https://python-poetry.org/) is installed, then
clone this repository.

Run `poetry install` to install the various dependencies.

## Basic usage

Check all sites with a verbose report:
```
poetry run licon -v check
```

Send reports by email:
```
poetry run licon email
```

Send the "Up" command to a light:
```
poetry run licon up haymakers/main/12
```

Set a group of lights to a particular level:
```
poetry run licon level haymakers/main/g2 128
```

Broadcast the "Off" command on a bus:
```
poetry run licon off haymakers/main
```
