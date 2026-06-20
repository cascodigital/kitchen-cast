# Roadmap / ideas

Loose list — this is a personal project developed in bursts.

- [x] Document the system as an AI-portable reference build rather than a generic installer.
- [ ] Recipe condensation for the TV overlay is currently naive (first ~12 lines of the `.txt`). Make it smarter: prioritize ingredients + the steps where mistakes happen, cap long steps. Optionally let the AI worker do the condensation.
- [x] Recipe library / session selection exists as the web app recipe picker plus active `music_recipe.json` handoff.
- [x] Reboot survival should be handled by Home Assistant restore state and renderer watchdogs in the real deployment; validate in your own target install.
- [ ] Crossfade / smoother transitions between frames. This is intentionally deferred because it likely requires changing the Chromecast delivery model.
- [ ] A physical button / NFC tag to arm the most-likely recipe without the phone.
- [ ] Make the photo slideshow's EXIF overlay (place, date) optional and configurable.
- [ ] Generalize the AI worker step so it's not tied to one specific LLM CLI.
- [ ] Health/status page for the renderers (are they alive? which state are we in?).
