# Venue

`venue.py --id <id>` decides the `Venue` value. Authors often do not update the arXiv comments
after acceptance, so a missing venue claim does not mean the paper is a preprint.

## Order of evidence

1. **Official accepted list** (title match: exact after normalization, or token overlap >= 0.9).
   Venue = `<conference> <year>`, plus `(Oral)` / `(Spotlight)` when the list says so.
2. **Claim in the arXiv comments or journal-ref** that no official list confirms: returned with
   `"verify": true`. Confirm it on the proceedings, OpenReview, the project page or the code README
   (`[CVPR 2026]` style labels). Workshop papers: `<conference> <year> Workshop`.
3. Otherwise `arXiv YYYY.MM` from the first submission date.

## Lists checked

With `venues: auto`, the submission year and the next year of:

| venue | source |
|---|---|
| ICLR, ICML, NeurIPS | `https://<conf>.cc/static/virtual/data/<conf>-<year>-orals-posters.json` |
| CVPR, ICCV (auto); WACV (only when listed in `venues`) | `https://openaccess.thecvf.com/<CONF><year>?day=all` (published at the conference) |
| ECCV | `https://www.ecva.net/papers.php` |

A list that is not out yet is skipped and retried after a day. Set `venues:` in the config to a
list such as `["ICLR 2026", "CVPR 2026"]` to check exactly those. For venues without a list here
(ACL, EMNLP, AAAI, ...), use step 2.

Lists are cached in `~/.cache/deep-paper/venues/` for 14 days; `venue.py --refresh` clears them.
