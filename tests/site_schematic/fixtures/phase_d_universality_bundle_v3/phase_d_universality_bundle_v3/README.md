# Phase D universality bundle (v3)

This bundle is meant to be **drop-in ready for Cursor**.

What is included:
- the two current benchmark PDFs already copied locally
- a registry seed for 10 public holdout packets (5 telecom/wireless, 5 low-voltage/security)
- pre-ingestion Phase A-D gold schemas for each holdout packet
- downloader scripts and a download manifest for the 10 public PDFs
- a full Phase A-D testing plan
- a detailed Cursor prompt to fetch, hydrate, integrate, and run the full suite

Important note:
- The 10 public holdout PDFs are **not embedded** in this bundle because this environment could not fetch external files.
- The included fetch scripts are intended to be run on your machine / in Cursor where external network access is available.
- The two current pair PDFs are already included under `pdfs/current_pair/`.
