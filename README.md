# Introduction 
This Python module allows control of the TVM 7675 Pro (SIGNATURE) series of MotionMount's from Vogel's Products.

# Getting Started
This module can be installed using the following command:
`pip install python-MotionMount`

In your Python code you can then use the module as follows:
```
import asyncio
import motionmount

ip = "MMF8A55F.local." # Can also be "169.254.13.16" or similar
port = 23 # The best way to get the port number is using zeroconf, but it's likely '23'

async def main():
    mm = MotionMount(ip, port)

    try:
        await mm.connect()
        await mm.go_to_preset(1)

        print(f"Extension: {mm.extension}")

        name = await mm.get_name()
        print(f"The name is: \"{name}\"")

        await mm.go_to_position(50, -50)
    except Exception as e:
        print(f"Something bad happened: {e}")
    finally:
        await asyncio.sleep(1)
        await mm.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
```

To get the IP address of the MotionMount you can use [pyzeroconf](https://github.com/paulsm/pyzeroconf) or you can use a manual tool like `dns-sd` in the macOS Terminal or a GUI tool like [Discovery](https://apps.apple.com/nl/app/discovery-dns-sd-browser/id1381004916?mt=12) (macOS) or [Bonjour Browser](https://hobbyistsoftware.com/bonjourbrowser) (Windows)
  
A simple example using `pyzeroconf` is included in the `examples` folder.
  
If you want to run the examples from a clone of the repository you can use a command similar to:
`PYTHONPATH=./src/motionmount python examples/simple.py`

# Changelog
1.0.1: - Fix bug in allowed preset indices

2.0.0: - Include position data in presets

2.1.0: - Add timeout (15 s) to `connect()`

2.2.0: - Add support for authentication to the MotionMount
