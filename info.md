<p align="center"><img src="brand/logo.png" alt="BetterJet" width="520"></p>

BetterJet connects Home Assistant to a BedJet V3 over Bluetooth LE.

- Holds one GATT connection for instant, local-push control.
- Reconnects automatically with backoff when the link drops.
- Defers standby temperature setpoints until the BedJet turns on.

The diagnostic Connection sensor shows which adapter or proxy carries the link.
The integration domain stays `bedjet` - upgrades in place with no entity changes.
