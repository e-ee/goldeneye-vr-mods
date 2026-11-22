# goldeneye-vr-mods

Optional copyright-safe asset packs downloaded on demand by GoldenEye VR's launcher (`ModManager`).

## Releases

### `lasersword-1.0`
- **Asset:** `lasersword-1.0.zip` containing `lasersword.bin` (`GEVRLS1\0`).
- **Contents:** Original procedural-industrial 3D energy-sword hilt mesh (`~300` triangles with baked vertex shading, exported cleanly for Blender customization via `--export-obj`) and five `22050 Hz` mono 16-bit PCM SFX clips (`hum`, `ignite`, `slash`, `deflect`, `clash`).
- **Rebuilding / Customizing:**
  ```sh
  python3 tools/gevr_lasersword_pack.py build/lasersword.bin --zip build/lasersword-1.0.zip
  # Or pack a custom Blender .obj hilt and WAV SFX:
  python3 tools/gevr_lasersword_pack.py build/lasersword.bin --obj custom_hilt.obj --wav-hum custom_hum.wav
  ```
