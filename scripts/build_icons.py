"""Create platform icon containers from the checked-in master artwork."""
from pathlib import Path
from PIL import Image

assets=Path(__file__).resolve().parents[1]/'hp48g'/'assets'
if __name__=='__main__':
    with Image.open(assets/'hp48gx-icon.png') as image:
        image.save(assets/'hp48gx-icon.ico',sizes=[(s,s) for s in (16,20,24,32,40,48,64,128,256)])
        image.save(assets/'hp48gx-icon.icns')
