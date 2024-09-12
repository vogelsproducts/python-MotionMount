import asyncio
import motionmount

ip = "MMF8A55F.local." # Can also be "169.254.13.16" or similar
port = 23 # The best way to get the port number is using zeroconf, but it's likely '23'


def callback():
    print("Update received")


async def main():
    global mm
    mm = motionmount.MotionMount(ip, port)
    mm.add_listener(callback)

    try:
        await mm.connect()
        await mm.go_to_preset(1)

        print(f"Extension: {mm.extension}")

        print(f"The name is: \"{mm.name}\"")
        print(f"The mac is: \"{mm.mac}\"")

        await mm.go_to_position(50, -50)
    except Exception as e:
        print(f"Something bad happened: {e}")
    finally:
        await asyncio.sleep(1)
        await mm.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
