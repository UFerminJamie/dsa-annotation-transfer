# HiPerGator to Athena annotation transfer

This tool reads JSON annotation documents from a directory on HiPerGator and attaches them to matching whole-slide image items in Athena through its annotation API. It matches each JSON filename to an Athena slide's sample name or image filename without the image extension, then records what it uploaded in a manifest.

## Directory structure

The source directory can be anywhere readable by the machine running the command. Put JSON files directly inside it, or use `--recursive` to include subdirectories.

```text
/path/to/your/annotations/
├── Sample_A_regions.json
├── Sample_A_heatmap.json
├── Sample_B_any_name.json
└── optional-subdirectory/
    └── Sample_C_annotations.json
```

The part after the sample name can be anything. The corresponding Athena destination can be a collection or folder containing the slides, including slides in descendant folders. For example, `Sample_A_regions.json` matches a slide named `Sample_A.svs`, an item with an image file named `Sample_A.tif`, or an item named `Sample_A` with large-image metadata. JSON documents must contain native DSA annotation data: one annotation object, one `{"annotation": {...}}` wrapper, or a list of those objects.

## Run step by step

1. On a HiPerGator node that can read your source directory and connect to Athena, install the tool:

   ```bash
   cd /path/to/HPG-ATHENA-Transfer
   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install -e .
   ```

2. Provide an Athena API key as `ATHENA_API_KEY` in the environment or in a local `.env` file in the directory where you run the command. For example, create the ignored `.env` file interactively:

   ```bash
   umask 077
   read -rsp 'Athena API key: ' ATHENA_API_KEY; printf '\n'
   printf 'ATHENA_API_KEY=%s\n' "$ATHENA_API_KEY" > .env
   unset ATHENA_API_KEY
   ```

3. Check authentication and access to your destination. Replace the example URL with your Athena collection or folder URL; keep browser URLs in quotes because they can contain `#`:

   ```bash
   hpg-athena-transfer --check-connection --destination 'https://athena.rc.ufl.edu/#collection/YOUR_COLLECTION_ID'
   ```

## Transfer Annotations

Below is a command for transferring annotations to uniquely matched slides in one Athena folder.

```bash
sbatch --account YOUR_ACCOUNT --partition YOUR_PARTITION run_transfer.sh 'https://athena.rc.ufl.edu/#folder/YOUR_FOLDER_ID' --source /path/to/your/annotations --apply
```

Note: A 401 usually indicates an invalid API key; a 403 usually indicates missing destination access or annotation permission.

## Download annotations from DSA to Hipergator

Download the selected annotation names from a DSA collection or folder, including nested folders. This writes JSON files locally. Existing output files are skipped unless `--overwrite` is supplied.

```bash
./download_dsa_annotation.sh \
  --url 'https://athena.rc.ufl.edu/#collection/YOUR_COLLECTION_ID' \
  --output-directory /path/to/downloaded_annotations
```

## Remove annotations

This helper previews active annotations whose names match its configured target-name list on WSIs in the selected Athena destination. Review the IDs and names, then add `--apply` to delete those records.

```bash
./remove_named_annotations.sh 'https://athena.rc.ufl.edu/#folder/YOUR_FOLDER_ID'
./remove_named_annotations.sh 'https://athena.rc.ufl.edu/#folder/YOUR_FOLDER_ID' --apply
```

Change the global variable `TARGET_NAMES` in `src/remove_named_annotations.py` to specify which annotations to remove in the item.

## Remove all annotations (Warning)

 Review the list before passing `--apply`; applying deletes all listed records regardless of name or provenance. The optional first argument selects the destination, and the script's configured destination is used when omitted.

```bash
./remove_annotations.sh 'https://athena.rc.ufl.edu/#folder/YOUR_FOLDER_ID'
./remove_annotations.sh 'https://athena.rc.ufl.edu/#folder/YOUR_FOLDER_ID' --apply
```

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests use synthetic annotations and a mocked Athena API.
