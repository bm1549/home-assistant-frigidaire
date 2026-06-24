# Frigidaire for Home Assistant

Connects your Frigidaire appliances to Home Assistant. If it's in your Frigidaire app, it shows up in HA — fridge, AC, whatever.

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![GitHub Release](https://img.shields.io/github/release/bm1549/home-assistant-frigidaire/all.svg?style=for-the-badge)](https://github.com/bm1549/home-assistant-frigidaire/releases)
[![License](https://img.shields.io/github/license/bm1549/home-assistant-frigidaire?style=for-the-badge)](LICENSE)
[![Maintainer](https://img.shields.io/badge/MAINTAINER-%40bm154969-red?style=for-the-badge)](https://github.com/bm1549)
[![Community Forum](https://img.shields.io/badge/COMMUNITY-FORUM-success?style=for-the-badge)](https://community.home-assistant.io)

## What it does

Once connected, your Frigidaire devices show up as climate entities in HA. You can see current temperature, target temperature, operating mode, and a few other things depending on the appliance. HA automations work too — turn off the AC when everyone leaves the house, start cooling before you get home, that kind of thing.

## Installing

### With HACS (easier)

If you already have [HACS](https://hacs.xyz/) set up:

1. In HA, go to HACS → Integrations
2. Click the three dots menu (⋮) → Custom repositories
3. Paste `https://github.com/bm1549/home-assistant-frigidaire` and pick **Integration** as the type
4. Click Add, then find Frigidaire in HACS and hit Install
5. Restart Home Assistant

### Without HACS

Clone the repo or just grab the `custom_components/frigidaire` folder:

```bash
git clone https://github.com/bm1549/home-assistant-frigidaire.git
cp -r home-assistant-frigidaire/custom_components/frigidaire /config/custom_components/
```

Restart Home Assistant.

## Setting it up

After the restart:

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Frigidaire**
3. It'll ask for your Frigidaire account — the same email and password you use in the Frigidaire app on your phone
4. Hit Submit

Your appliances should show up as climate entities. If you have multiple Frigidaire devices, they'll each get their own entity.

## If something goes wrong

- **Integration doesn't show up in the list?** Restart HA one more time. Also double-check the folder path — it should be `/config/custom_components/frigidaire/`, not nested deeper.
- **Login keeps failing?** Make sure you're using the same email and password as the Frigidaire mobile app. No extra spaces.
- **No devices after a successful login?** Open the Frigidaire app and confirm your appliances are online there. If the app can't see them, HA won't either.
- **HACS says "pending merge"?** That's normal — HACS integration is in progress. Manual install works fine in the meantime.

## Other stuff

Check [Releases](https://github.com/bm1549/home-assistant-frigidaire/releases) for version history and changelog.

Found a bug or have an idea? Open an [issue](https://github.com/bm1549/home-assistant-frigidaire/issues). PRs are welcome too.

MIT License.
