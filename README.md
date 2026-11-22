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

### `lsninja-1.0`
- **Asset:** `lsninja-1.0.zip` containing `lasersword_ninja.bin` (`GEVRLN1\0`).
- **Contents:** Seven original copyright-safe 3D weapon meshes (`hilt_single`, `hilt_double`, `katana_silver`, `katana_gold`, `shield`, `shuriken`, `wing`, `1592` triangles total with baked vertex shading, exportable to `.obj` for Blender via `--export-obj-dir`) and twelve `22050 Hz` mono 16-bit PCM SFX clips (four seamless loops: `hum`, `force_rumble`, `lightning`, `spin`; eight one-shot events: `ignite`, `slash_lasersword`, `slash_steel`, `deflect`, `clash_lasersword`, `clash_metal`, `force_push`, `shadow_step`).
- **Rebuilding / Customizing:**
  ```sh
  python3 tools/gevr_lasersword_ninja_pack.py build/lasersword_ninja.bin --zip build/lsninja-1.0.zip
  # Or export .obj meshes and override any WAV clip:
  python3 tools/gevr_lasersword_ninja_pack.py build/lasersword_ninja.bin --export-obj-dir obj/ --wav-dir wavs/
  ```

