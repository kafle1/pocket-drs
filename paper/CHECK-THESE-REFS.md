# References added for the TIM screening

Thirteen new references were added and one existing DOI was corrected. Everything below was checked
against Crossref, OpenAlex and Semantic Scholar: title, authors, journal, volume, issue, pages, year
and DOI all resolve. Two entries are flagged at the bottom because the publisher blocked the abstract.

Last checked: 2026-09-18. Paper cites 34 references and builds to 8 pages.

## What each new reference is used to claim

| Key | Reference | DOI | What the paper says it shows |
|---|---|---|---|
| carullo2024conformity | Carullo et al., *IEEE Instrumentation & Measurement Magazine* 27(4) 5-12, 2024 | [10.1109/MIM.2024.10540404](https://doi.org/10.1109/MIM.2024.10540404) | Measurement uncertainty enters a statement of conformity; a guard band moves the acceptance limit |
| zhu2022smartphone6dof | Zhu et al., *IEEE Transactions on Instrumentation and Measurement* 71 1-14, 2022 | [10.1109/TIM.2022.3200432](https://doi.org/10.1109/TIM.2022.3200432) | Six degrees of freedom of a moving rigid body measured from smartphone cameras |
| arik2022mobilecalib | Arik and Yuksel, *IEEE Transactions on Instrumentation and Measurement* 71 1-8, 2022 | [10.1109/TIM.2022.3204309](https://doi.org/10.1109/TIM.2022.3204309) | A mobile camera calibrated from scene structure and the onboard accelerometer, not a printed target |
| huang2025monotraj | Huang et al., *Measurement* 256 118136, 2025 | [10.1016/j.measurement.2025.118136](https://doi.org/10.1016/j.measurement.2025.118136) | 3-D trajectory of moving points from one camera |
| wang2024quasi1d | Wang et al., *Measurement Science and Technology* 35(12) 125903, 2024 | [10.1088/1361-6501/ad76cc](https://doi.org/10.1088/1361-6501/ad76cc) | A high-speed object measured with a steered (galvo) mirror |
| guo2026pose | Guo et al., *Measurement* 277 121521, 2026 | [10.1016/j.measurement.2026.121521](https://doi.org/10.1016/j.measurement.2026.121521) | Pose of a high-speed object from unsynchronised sequences on independently moving platforms |
| zhu2026tennis | Zhu et al., *Measurement* 275 121259, 2026 | [10.1016/j.measurement.2026.121259](https://doi.org/10.1016/j.measurement.2026.121259) | Tennis ball speed and spin from a single camera |
| sun2024rebound | Sun et al., *IEEE Transactions on Instrumentation and Measurement* 73 1-11, 2024 | [10.1109/TIM.2024.3381294](https://doi.org/10.1109/TIM.2024.3381294) | Velocity-dependent restitution in a ball-racket rebound model |
| dileo2011covariance | Di Leo et al., *IEEE Transactions on Instrumentation and Measurement* 60(5) 1664-1673, 2011 | [10.1109/TIM.2011.2113070](https://doi.org/10.1109/TIM.2011.2113070) | Covariance propagated through stereo triangulation |
| ezebili2024uncertainty | Ezebili and Schreve, *Measurement Science and Technology* 35(4) 045032, 2024 | [10.1088/1361-6501/ad20bf](https://doi.org/10.1088/1361-6501/ad20bf) | Analytic uncertainty propagation for convergent stereo |
| he2026binocular | He et al., *Measurement* 290 122909, 2026 | [10.1016/j.measurement.2026.122909](https://doi.org/10.1016/j.measurement.2026.122909) | Binocular uncertainty predicted from a first-order linearised covariance |
| alosman2021mluq | Al Osman and Shirmohammadi, *IEEE Instrumentation & Measurement Magazine* 24(3) 23-27, 2021 | [10.1109/MIM.2021.9436102](https://doi.org/10.1109/MIM.2021.9436102) | Quantify what a learned component contributes to measurement uncertainty |
| buchicchio2025uq | Buchicchio et al., *IEEE Instrumentation & Measurement Magazine* 28(3) 52-59, 2025 | [10.1109/MIM.2025.10982089](https://doi.org/10.1109/MIM.2025.10982089) | Uncertainty quantification in AI-based measurement systems |
| wang2024extrinsicerror | Wang et al., *Measurement* 229 114413, 2024 | [10.1016/j.measurement.2024.114413](https://doi.org/10.1016/j.measurement.2024.114413) | How camera extrinsic error affects monocular measurement accuracy |

## Two to eyeball before you send

Both are Elsevier papers whose abstract page refuses automated access, so the claim rests on the title
and on search-engine text rather than on the publisher's own abstract.

- **he2026binocular.** The paper calls this "the device used here". Title confirms first-order linearised
  covariance for binocular vision. Nothing stronger was obtainable.
- **zhu2026tennis.** Speed and spin from a single camera at 100 fps is confirmed by two independent
  search results. Table I lists its mount as fixed, which follows from the described setup but is not
  stated in anything obtainable.

## Corrected

`dileo2011covariance` carried DOI `10.1109/TIM.2011.2158103` in the submitted version. That DOI does not
resolve. The correct one is `10.1109/TIM.2011.2113070`, confirmed against Crossref.

## Dropped from the original submission

Ten references were removed to make room, all of them sport-tracking or generic computer vision that the
repositioning no longer leans on: calandre2021tabletennis, chao2023basketball, chen2023tracknetv3,
collins2008hawkeye, hartley2004mvg, huang2019tracknet, lepetit2009epnp, liu2022monotrack,
ponglertnapakorn2025ball, redmon2016yolo.

`mi2021vbm` was researched, added, then removed: it is a survey of vision-based measurement in automated
container terminals and does not support the general claim the draft made with it.

## Entries in refs.bib that nothing cites

Eighteen verified entries stay in `refs.bib` uncited. BibTeX ignores them, so they cost nothing, and they
are the bench to draw from if a reviewer asks for more: the ten dropped above, plus mi2021vbm,
deng2020spinning, feng2025errorprop, he2024orthopedic, hong2025outline, jiang2021uncertainty,
xia2020vmp, yang2024monopstr.
