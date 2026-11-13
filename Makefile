# One command reruns the pilot from the PDF:  make pilot
UV ?= uv
PY  = $(UV) run python

.PHONY: pilot recon select extract reference score review test clean-cache

pilot: recon select extract test reference score review

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
