

A Blender addon that generates AI-driven human motion via [NVIDIA Kimodo](https://github.com/nv-tlabs/kimodo) and imports it directly into your scene — no copy-pasting, no manual BVH wrangling.

## Star History

<a href="https://www.star-history.com/?repos=lewdineer%2FKimodo_Blender_Bridge&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=lewdineer/Kimodo_Blender_Bridge&type=date&theme=dark&legend=top-left&sealed_token=gg3e8bjBVO1mASsY7F2FfwXezEB5zKIehjMw-s8K0AeGqeg94JCIRoPyBtxv55OxO9Pvi5cFwEyXXpA7wOwC8khA42N0EIz--WX4-WLBhTkFav2p97mv0gNKScQBzfaLta9xHnw9ELr6Ntm0RTGEbBvwvSp8RubVcK10aKSlsQs3pwmd4LuWqQp0kpux" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=lewdineer/Kimodo_Blender_Bridge&type=date&legend=top-left&sealed_token=gg3e8bjBVO1mASsY7F2FfwXezEB5zKIehjMw-s8K0AeGqeg94JCIRoPyBtxv55OxO9Pvi5cFwEyXXpA7wOwC8khA42N0EIz--WX4-WLBhTkFav2p97mv0gNKScQBzfaLta9xHnw9ELr6Ntm0RTGEbBvwvSp8RubVcK10aKSlsQs3pwmd4LuWqQp0kpux" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=lewdineer/Kimodo_Blender_Bridge&type=date&legend=top-left&sealed_token=gg3e8bjBVO1mASsY7F2FfwXezEB5zKIehjMw-s8K0AeGqeg94JCIRoPyBtxv55OxO9Pvi5cFwEyXXpA7wOwC8khA42N0EIz--WX4-WLBhTkFav2p97mv0gNKScQBzfaLta9xHnw9ELr6Ntm0RTGEbBvwvSp8RubVcK10aKSlsQs3pwmd4LuWqQp0kpux" />
 </picture>
</a>

## Links / Video guide
Youtube tutorial: https://youtu.be/nbiaS43Ncng
Superhive: https://superhivemarket.com/products/kimodoblenderbridge

---

## Tested on 
**Blender 5.1 / 4.4**

**Arch Linux RTX 3090 Python 3.12**

**Windows 11 RTX 1080 Python 3.12**

**Windows 11 RTX 5070 Python 3.13**

<img width="1237" height="1257" alt="image" src="https://github.com/user-attachments/assets/71a1666d-a460-40eb-af23-1dbb8ab750cb" />


---

## How it works

Blender's embedded Python cannot load PyTorch or Kimodo directly. The addon solves this with a two-process bridge:

```
Blender (addon)                Kimodo venv
  subprocess_client.py  ─────▶  bridge_server.py
                        ◀─────  (model loaded once, handles requests)
```

The bridge server loads the Kimodo model once at startup and then responds to generation requests over stdin/stdout. Blender stays responsive while generation runs in a background thread.

---

## Requirements

| Requirement | Notes |
|---|---|
| Blender 4.0+ | Tested on 5.1 (Windows & Arch Linux) |
| Python 3.10–3.12 | System Python used to create the managed venv |
| NVIDIA GPU | 8 GB+ VRAM recommended; 16 GB+ for best results |
| CUDA | Must match your PyTorch build (CUDA 12.1 installed by default) |
| ~10 GB disk | For the managed venv, model weights, and LLM2Vec encoder |

> **Low VRAM?** Run `kimodo_textencoder --device cpu` in a separate terminal with the Kimodo venv activated. This offloads the text encoder to CPU and frees several GB of VRAM.

---

## Installation

As of v1.2.0 Kimodo installs itself automatically — no terminal required. The addon is also compatible with the Blender 4.2+ Extensions platform (includes `blender_manifest.toml`).

### 1 — Install the Blender addon

1. Download or clone this repository (top-right **Code → Download ZIP**).
2. Open Blender → **Edit → Preferences → Add-ons → Install from Disk…**
3. Select the downloaded zip and enable **"Kimodo Motion Generator"**.

### 2 — Click "Install Kimodo (Auto)"

Open the **Kimodo** N-Panel tab (press `N` in the 3D Viewport), expand **Connection**, and click **Install Kimodo (Auto)**.

The installer will:
- Create a managed Python venv at `~/.kimodo-venv/`
- Install PyTorch (CUDA 12.1), all Kimodo dependencies, and the [Aero-Ex offline fork](https://github.com/Aero-Ex/kimodo)
- Download the LLM2Vec text-encoder model locally and patch it for offline use
- Download the `Kimodo-SOMA-RP-v1` model weights into the HF cache
- Set the Python path automatically when done

Progress is shown live in the Connection panel. The full log is printed to the system console (launch Blender from a terminal, or on Windows use **Window → Toggle System Console**).

> **Requires:** Python 3.10–3.12 on your system PATH, internet access, and ~10 GB of free disk space. After the initial install, Kimodo runs fully offline.

### Manual installation (advanced)

If you already have Kimodo installed in your own venv, skip the auto-installer and paste the path to your venv Python into the **Kimodo Python** field in the Connection panel.

---

## Quick Start

### Generate motion from a text prompt

1. **Start** the bridge: click **Start Kimodo** in the Connection panel.  
   The status line will show *Loading model…* then *Ready* once the model is loaded (this takes 10–60 s the first time).

2. Open the **Motion Segments** panel.

3. Click **Add** to create a segment, type a prompt (e.g. `a person jogs in a circle`), and set the frame range.

4. Click **Generate Selected** (one segment) or **Generate All** (all enabled segments in one model call with smooth transitions).

5. A `Kimodo_Source` armature will appear in your scene with the generated motion applied.

> **30 FPS tip:** Kimodo always generates at 30 FPS. If your scene is set to a different frame rate, an alert will appear above the generate buttons with a **Set to 30 FPS** button.

### Use multiple segments

Each segment is an independent text prompt mapped to a frame range. **Generate All** sends every enabled segment to Kimodo in a single model call, producing one continuous animation with smooth transitions between prompts.

- Segments are listed in order. The **Start** frame of each segment after the first is automatically locked to the **End** frame of the previous segment — just drag the End frame and the next segment's Start updates automatically.
- Use **Duplicate** to copy a segment and place it immediately after.
- Use **↑ / ↓** to reorder segments.

<img width="2676" height="1181" alt="image" src="https://github.com/user-attachments/assets/a5d336e9-f32f-44c7-9aca-a09983e869d6" />


### Retarget to your own rig

After generating motion you can drive any armature from the Kimodo source:

1. Open the **Retarget** panel.
2. Set **Source** to `Kimodo_Source` and **Target** to your character rig.
3. Choose **Auto Detect**, **Unreal UE5**, or **Reallusion CC / iClone**, then click **Build Profile Mapping**.
4. Review the mapping, enable/disable pairs, choose a retarget mode per bone. Its recommended to also adjust the scale of the armature to match your character and then applying it with CTRL+A.
5. Choose the type of constraint the plugin should use, "Child of", "Copy Rotation" etc...
6. Click **Apply Constraints** — Blender constraint drivers are added to your rig.
7. Click **Bake & Remove Constraints** when you are happy — keyframes are baked onto your rig and all Kimodo constraints are removed, leaving a clean, self-contained animation.

Use **Save / Load Preset** to store bone mappings for a rig and reuse them later.

The built-in Unreal profile targets the **UE5 Manny hierarchy** (`root`, `pelvis`,
`spine_01`...`spine_05`) and also supports Reallusion characters exported with
**Unreal (UE5 Skeleton)**. The native Reallusion profile targets the
`CC_Base_*` hierarchy used by Character Creator and iClone. The built-in
Unreal profile is UE5-only.

Before applying constraints, place the source and target in matching reference
poses. Epic recommends matching retarget poses when proportions or base poses
differ. Reallusion users should select **Unreal (UE5 Skeleton)** during export.

Official references:

- [Epic: Retargeting Bipeds with IK Rig](https://dev.epicgames.com/documentation/unreal-engine/retargeting-bipeds-with-ik-rig-in-unreal-engine)
- [Epic: Skeletons in Unreal Engine](https://dev.epicgames.com/documentation/en-us/unreal-engine/skeletons-in-unreal-engine)
- [Reallusion: Exporting Characters from iClone or Character Creator](https://manual.reallusion.com/CC-iC-Auto-Setup/All-in-One/1.2/02_for_Unreal/Exporting-Characters-from-iC-or-CC.htm)

### Send Kimodo motion to iClone through official Data Link

The primary workflow uses **Reallusion Blender Auto Setup 2.4.0** on both sides.
The iClone character is imported into Blender once, so Kimodo is retargeted on
the character's actual 101-bone CC skeleton before Reallusion creates the
iClone Motion Clip.

1. Start **Blender Pipeline / Data Link** in iClone and Blender.
2. Select the iClone character and send it to Blender with the official plugin.
3. In Blender **Retarget**, choose Kimodo as **Source** and the imported CC rig as **Target**.
4. Click **Send Motion to iClone**.

The add-on bakes the complete Kimodo Action onto the CC rig, including root
translation, then asks the official Data Link to send the 30 fps animation
sequence. iClone receives one ordinary Motion Clip. This avoids applying SOMA
rotations directly through iClone HIK, which can rotate the arm and hand chains.

The older **Manual FBX Fallback** remains available for offline interchange.
It exports an animation-only FBX and companion `.3dxProfile` for iClone's
**Import External Motion** command.

Official reference:

- [iClone 8: Importing External Motions](https://manual.reallusion.com/iClone-8/Content/ENU/8.4/50-Animation/Import-External-Motions/Import-External-Motions.htm)

<img width="1233" height="839" alt="image" src="https://github.com/user-attachments/assets/d76290db-7662-4223-9cd6-7083f89b35ca" />

### Motion constraints

Spatial goals can be given to Kimodo so the generated motion passes through specific positions:

| Constraint | What it controls |
|---|---|
| Root XZ | Where the character's root lands on the ground plane |
| Full-Body | A full joint-pose keyframe (pose a reference armature) |
| Left / Right Hand | Wrist end-effector position |
| Left / Right Foot | Foot / heel end-effector position |

To add a constraint:
1. Move the 3D cursor (or select an armature) to the desired position.
2. Set the timeline to the target frame.
3. In the **Motion Constraints** panel, click the constraint type.

**Auto-Origin** (off by default) shifts all constraint positions so the earliest root waypoint lands at Kimodo's world origin — author constraints anywhere in your scene without worrying about absolute coordinates.

---

## Panel reference

| Panel | What's in it |
|---|---|
| **Connection** | Kimodo Python path, model selector, Start / Stop bridge |
| **Motion Segments** | Prompt list, frame ranges, Generate Selected / Generate All |
| **Quick Generate** | Single-prompt generation with duration and seed controls |
| **Motion Constraints** | Spatial waypoints for the generated motion |
| **Retarget** | Bone mapping, CC-rig bake, official iClone Data Link transfer, manual FBX fallback |
| **Help** | Quick-start checklist, VRAM tip |

---

## Troubleshooting

**Bridge won't start / "Failed to start"**
- Check the system console for `[Kimodo Bridge]` lines — the full Python/PyTorch error is printed there.
- Check that the Python path points to the venv Python that has Kimodo installed.
- If you used the auto-installer and it failed partway through, click **Retry Install** — it will wipe the partial venv and start clean.

**CUDA out of memory**
- Use a shorter duration or fewer segments.

**Retargeted rig is in the wrong pose**
- Try a different retarget mode per bone (Copy Rotation vs Copy Transforms vs Child Of).
- Make sure the source and target armatures are both in their rest pose / have the same pose before trying the retargeting, and have scale applied on the armature.

**Frames from imorted animation dont match**
- Kimodo generates at exactly 30 FPS. Use the **Set to 30 FPS** button that appears in the Motion Segments panel when your scene is at a different frame rate.

---

## File overview

| File | Role |
|---|---|
| `__init__.py` | Blender addon entry point |
| `bridge_server.py` | Subprocess: loads Kimodo, handles generation requests |
| `subprocess_client.py` | Blender-side bridge manager |
| `operators.py` | All `bpy.ops.kimodo.*` operators |
| `properties.py` | All `bpy.props` scene settings |
| `panels.py` | N-panel UI |
| `constraints.py` | Converts Blender constraint markers to Kimodo JSON |
| `retarget.py` | Applies / bakes retargeting constraints |
| `retarget_presets.py` | Built-in Unreal UE5 and Reallusion CC/iClone skeleton maps |
| `iclone_live_send.py` | Live CC rest-axis sampling and direct Motion Clip transfer |
| `iclone_motion_export.py` | Standalone FBX + 3DX motion export for iClone |
| `iclone_plugin/kimodo_motion_receiver/` | Restricted iClone OpenPlugin receiver |
| `ui_list.py` | UIList helper for the bone mapping panel |
| `setup_operator.py` | One-click auto-installer for Kimodo and all dependencies |

---

## License

See [LICENSE](LICENSE).
