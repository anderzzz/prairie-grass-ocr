# One command reruns the pilot from the PDF:  make pilot
UV ?= uv
PY  = $(UV) run python

.PHONY: volume2-followup pilot recon select extract reference score score-holdout review test clean-cache volume dataset notebooks volume2 volume2-review volume2-dataset volume1s volume1s-dataset annotations reference-comparison review-round2 review-round3

pilot: recon select extract test reference score review   # full pilot incl. holdout: git checkout pilot-v1 && make pilot

recon:            ## page map + table-page inventory (docs/)
	$(PY) -m extract.recon

select:           ## rule-based pilot pages (kept if config/pilot_pages.yaml exists)
	$(PY) -m extract.select_pages

extract:          ## Mistral + offline readers, flags -> output/extracted, output/crops, output/pages
	$(PY) -m extract.pipeline --set all

reference:        ## answer key -> reference/ (gitignored), with SHA-256 checksums
	$(PY) scripts/fetch_reference.py

score:            ## compare dev pages with reference -> output/scores (holdout: make score-holdout)
	$(PY) -m scoring.score

review:           ## static HTML review pack -> review/
	$(PY) -m scoring.review

test:
	$(UV) run pytest -q

clean-cache:
	rm -rf cache

score-holdout:    ## once, after the extraction-frozen tag
	$(PY) -m scoring.score --set holdout

volume:           ## all Volume I table pages -> output/volume1 (post-pilot)
	$(PY) scripts/run_volume.py
	$(PY) -m scoring.volume_compare

dataset:          ## reviewed Volume I dataset (extraction + owner verdicts; no reference) -> output/volume1/dataset
	cd src && $(PY) -m dataset.build

annotations:      ## curators' statements on the datasets (suspects, errata, keys, doubtful readings) -> output/publish/annotations.jsonl
	cd src && $(PY) -m publish.annotations

reference-comparison: ## cells where Volume I and the harmo.org reference differ (needs make reference) -> output/publish/reference_comparison.csv
	$(PY) -m scoring.reference_comparison

review-round2:    ## owner review pack: doubtful readings + outliers (no reference) -> review/round2/index.html
	cd src && $(PY) -m publish.review_pack

review-round3:    ## owner review pack: what round 2 left open, cells located from the print -> review/round3/index.html
	cd src && $(PY) -m publish.review_round3

notebooks:        ## exploration notebooks (needs `make dataset` first)
	$(UV) run --group notebooks jupyter lab notebooks/

volume2:          ## Volume II: Mistral OCR (cached) -> parsed tables -> consistency checks -> output/volume2
	cd src && $(PY) -m volume2.ocr && $(PY) -m volume2.run && $(PY) -m volume2.checks

volume2-review:   ## Sonnet second reading of rows in failed checks (capped, cached) + owner review pack -> review/volume2
	cd src && $(PY) -m volume2.second_read && $(PY) -m volume2.review

volume2-followup: ## full Sonnet reading of Tables 8.1/8.2 (cached) + settle disagreements by context -> config/review/volume2_followup.csv
	cd src && $(PY) -m volume2.second_read && $(PY) -m volume2.followup

volume2-dataset:  ## Volume II dataset (after review: DATE=yyyy-mm-dd make volume2-dataset) -> output/volume2/dataset
	cd src && $(PY) -m volume2.dataset $(if $(DATE),--resolve $(DATE),) && $(PY) -m volume2.outliers

volume1s:         ## Vol I Tables 5.1, 5.4, 6.1: Mistral + full Sonnet second reading (cached) -> checks -> review pack
	cd src && $(PY) -m volume1s.ocr && $(PY) -m volume1s.second_read && $(PY) -m volume1s.compare && $(PY) -m volume1s.checks && $(PY) -m volume1s.review

volume1s-dataset: ## Vol I supplementary dataset (after review: DATE=yyyy-mm-dd make volume1s-dataset) -> output/volume1/dataset
	cd src && $(PY) -m volume1s.dataset $(if $(DATE),--resolve $(DATE),)
