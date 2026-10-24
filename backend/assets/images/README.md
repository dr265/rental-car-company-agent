# Fleet photos the agent can send

Every picture in this folder is available to the agent. The file name *is* the
registry id, so the agent addresses photos by name — never by an absolute path.
WhatsApp cannot read a local file system: a picture can only be delivered as a
public link or by uploading the bytes to the Cloud API, and the agent does both
automatically from here.

**Supported formats:** PNG, JPG/JPEG, WEBP (the real format is verified from the
file's magic bytes, so a mislabelled `.jpg` that is really a PNG is rejected
rather than sent broken). **Maximum size:** `MAX_IMAGE_BYTES` (8 MB by default).

---

## The ZoomRideXX rate-card fleet

| Registry id | Vehicle | Label shown to the customer |
| --- | --- | --- |
| `thar-roxx` | Mahindra Thar Roxx | Mahindra Thar Roxx |
| `thar-4x4` | Mahindra Thar 4x4 | Mahindra Thar 4x4 |
| `scorpio-n` | Mahindra Scorpio N | Mahindra Scorpio N |
| `scorpio-s11` | Mahindra Scorpio S11 | Mahindra Scorpio S11 |
| `xuv-700` | Mahindra XUV 700 | Mahindra XUV 700 |
| `endeavour` | Ford Endeavour | Ford Endeavour |
| `fortuner` | Toyota Fortuner | Toyota Fortuner |
| `ertiga` | Maruti Ertiga | Maruti Ertiga |
| `fronx` | Maruti Fronx | Maruti Fronx |
| `dzire` | Maruti Dzire | Maruti Dzire |
| `baleno` | Maruti Baleno | Maruti Baleno |
| `swift` | Maruti Swift | Maruti Swift |
| `aura` | Hyundai Aura | Hyundai Aura |
| `brezza` | Maruti Brezza | Maruti Brezza |
| `creta` | Hyundai Creta | Hyundai Creta |
| `verna` | Hyundai Verna | Hyundai Verna |
| `venue` | Hyundai Venue | Hyundai Venue |

Labels live in `LABELS` in [`media.py`](../../app/media.py). Captions shown to
the customer use them, so name the car only — never "photo" or "reference".

---

## How the agent chooses which photo to send

When a vehicle is quoted — or the customer asks to see one — the agent resolves
a picture in this order, first hit wins:

| # | Source | Example |
|---|--------|---------|
| 1 | The fleet row's `image_url`, when it is a public link | `https://yourhost/media/assets/creta.jpg` |
| 2 | The fleet row's `image_url`, when it names a registry id | `creta` |
| 3 | The model name in the fleet row | `Hyundai Creta` → `creta.jpg` |
| 4 | The category | `SUV` → an SUV photo |

The seeded fleet rows already point at their ids, so every car card, quote and
booking confirmation attaches the right picture. The "see all cars" gallery
sends all 17 as one swipeable album in the console and a burst of image bubbles
on WhatsApp (WhatsApp has no native album).

---

## Three ways to add a photo

1. **Drop the file in here** and restart the agent. Name it after the car, e.g.
   `creta.jpg`. Nothing else to configure.
2. **Upload from the owner console** — stored in `<data>/uploads/images` and
   picked up immediately, no restart. Use the model name in the file name to
   bind it to that car.
3. **Edit the vehicle in the Fleet tab** and set its image to the registry id.

Check what the agent can currently see, and where it will send it from:

    http://localhost:8022/api/media

That endpoint lists every usable photo with its id, label and ready-to-use URL,
and reports whether images go out as a public link or as a direct WhatsApp
media upload (relevant on localhost, where WhatsApp cannot fetch a link).

---

## Deleting

Files here are *shipped* assets — the console will not delete them (that would
break the app after a reinstall). Delete the file itself and restart. Photos
uploaded through the console *are* deletable from the console.
