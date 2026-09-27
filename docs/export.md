# Downloading learned weights

Verified on 2026-09-27 against River's official documentation and the installed `river-client==0.11.0` package.

## Supported export path

River documents weight download through its Console:

1. Open the [River Console](https://console.river.ai/).
2. Open **Checkpoints**.
3. Select the **inference checkpoint** whose `river://` identifier matches the Reflex checkpoint.
4. Use that checkpoint's **download action**.
5. Save the downloaded artifact inside a private location in this repository, such as `data/exports/<checkpoint-name>/`.

River says this download contains LoRA adapter weights in PEFT format. The adapter needs the corresponding base model. A `river://` identifier addresses River's internal checkpoint; it is not a public download URL. [Official Console and download instructions](https://docs.river.ai/guides/operations/)

The Console download was documented but not executed during implementation. This project has not downloaded or validated any trained adapter yet.

## Why Reflex does not offer a direct SDK download

The installed `river-client==0.11.0` exposes checkpoint save/load and inference operations, but no public weight-download/export method. Its package source, public `Client`/`Session`/`Model`/`Checkpoint` members, and generated RPC declarations were inspected. The [current Python reference](https://docs.river.ai/python-api/) also documents no download method.

Consequently there is no implemented `export_checkpoint(checkpoint, destination)` helper and no invented HTTP endpoint. A downloaded JSON manifest, dataset, or `river://` address must not be labeled as exported model weights. A future direct integration needs a documented download API, authenticated artifact response, and a tested size-bounded streaming path.

## Keep enough information to reuse the adapter

Save the following alongside the downloaded files from the matching Reflex checkpoint and training/evaluation records:

- Exact River checkpoint identifier and name, creation time, and inference checkpoint type.
- Base-model identifier and, when available, immutable base-model revision.
- Tokenizer revision, rendering configuration, and generation settings.
- LoRA rank and initialization seed, training method, optimizer settings, and SDK version.
- Training dataset hash and the matching evaluation artifact.
- A SHA-256 digest of each downloaded file after download completes.

These are Reflex's provenance requirements. The audit did not establish that River's archive automatically contains all of them. Inspect the real artifact before making that claim. Do not silently substitute a different base-model revision: an adapter alone is not a complete standalone model. [River adapter guide](https://docs.river.ai/guides/lora/)

River's public `save_weights` reference specifies a default and maximum checkpoint lifetime of one year. Exporting the actual artifact is therefore distinct from retaining its remote identifier. [Checkpoint lifetime reference](https://docs.river.ai/python-api/)

## Evidence required before reporting a successful local export

- The Console supplied a download for the selected inference checkpoint.
- All files finished downloading; file sizes and hashes were recorded.
- The artifact contains actual adapter tensors and the configuration required by its PEFT format.
- The adapter's base-model lineage matches the recorded training run.
- A separate local inference check confirms that the downloaded artifact loads with that base model before claiming local portability has been demonstrated.

No paid request, Console download, or local-model load was performed by this research. The supported user action is the documented Console download; local portability remains unverified until the artifact is available.
