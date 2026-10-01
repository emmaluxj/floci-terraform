import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    try:
        urlopen("http://floci:4566/", timeout=2)
        print("Floci is accepting requests.")
        break
    except HTTPError:
        print("Floci is accepting requests.")
        break
    except URLError:
        time.sleep(2)
else:
    raise SystemExit("Floci did not become available within 120 seconds.")
