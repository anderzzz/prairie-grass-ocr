# One command reruns the pilot from the PDF:  make pilot
UV ?= uv
PY  = $(UV) run python

.PHONY: pilot recon select extract reference score review test clean-cache

pilot: recon select extract test reference score review

recon:            ## page map + table-page inventory (docs/)
	$(PY) -m extract.recon

select:           ## rule-based pilot pages (kept if config/pilot_pages.yaml exists)
	$(PY) -m extract.select_pages

extract:          ## readers, consensus, flags -> output/extracted, output/crops
	$(PY) -m extract.pipeline --set all

reference:        ## answer key -> reference/ (gitignored), with SHA-256 checksums
	$(PY) scripts/fetch_reference.py

score:            ## compare with reference -> output/scores
	$(PY) -m scoring.score

review:           ## static HTML review pack -> review/
	$(PY) -m scoring.review

test:
	$(UV) run pytest -q

clean-cache:
	rm -rf cache
