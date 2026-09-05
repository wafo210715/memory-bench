import sys, asyncio, pathlib
from playwright.async_api import async_playwright

async def main(svgs):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(device_scale_factor=2)
        for s in svgs:
            s = pathlib.Path(s)
            await pg.goto(s.resolve().as_uri())
            el = await pg.query_selector("svg")
            box = await el.bounding_box()
            await pg.set_viewport_size({"width": int(box["width"]) + 4, "height": int(box["height"]) + 4})
            out = s.with_suffix(".png")
            await el.screenshot(path=str(out))
            print(out, out.stat().st_size // 1024, "KB")
        await b.close()

asyncio.run(main(sys.argv[1:]))
