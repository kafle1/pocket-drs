# Candidate references for PocketDRS

Your bibliography is 14 entries. IEEE journals typically expect 30 to 50 for a full paper, and a
reviewer will notice the related work is thin, particularly on sports ball tracking where there is
a real literature you are not engaging with.

**Read these before you cite them.** Every DOI below was verified against OpenAlex and resolves, but
a citation you have not read is worse than a short bibliography: reviewers ask about them, and being
unable to discuss a paper you cited is the kind of thing that sinks a revision. Cite the ones that
genuinely bear on your argument and drop the rest.

## Closest to your problem: ball tracking and trajectory from video

| Paper | Why it matters to you | DOI |
|---|---|---|
| Ball Tracking and Trajectory Prediction for Table-Tennis Robots (Sensors, 2020) | Same problem shape: fast small ball, physics-constrained prediction. Their accuracy is your natural comparison. | `10.3390/s20020333` |
| Reliable Real-Time Ball Tracking for Robot Table Tennis (Robotics, 2019) | Real-time tracking with an explicit bounce model. | `10.3390/robotics8040090` |
| Online optimal trajectory generation for robot table tennis (RAS, 2018) | Trajectory fitting under a restitution bounce, close to your solver. | `10.1016/j.robot.2018.03.012` |
| Ball Motion Control in the Table Tennis Robot System Using Time-Series Models (IEEE Access, 2021) | Alternative to your per-arc fit. | `10.1109/access.2021.3093340` |
| A deep learning ball tracking system in soccer videos (Opto-Electron. Rev., 2019) | Detection of a small ball in cluttered broadcast video. | `10.1016/j.opelre.2019.02.003` |
| Small Object Detection and Tracking: A Comprehensive Review (Sensors, 2023) | Survey that frames your detection problem; useful in Related Work. | `10.3390/s23156887` |
| HOTA: A Higher Order Metric for Evaluating Multi-object Tracking (IJCV, 2020) | If a reviewer asks how you evaluate tracking rather than reconstruction. | `10.1007/s11263-020-01375-2` |

## Cricket-specific computer vision

| Paper | Why it matters to you | DOI |
|---|---|---|
| Deep Transfer Learning-Based Foot No-Ball Detection in Live Cricket (2023) | The closest published work on automated cricket officiating. You should cite and contrast this. | `10.1155/2023/2398121` |
| Enhancing Cricket Performance Analysis with Human Pose Estimation (Sensors, 2023) | Cricket video analysis, adjacent scope. | `10.3390/s23156839` |
| Optimized deep learning-based cricket activity focused network (Alex. Eng. J., 2023) | Cricket action recognition from video. | `10.1016/j.aej.2023.04.062` |

## Validating optical tracking against ground truth

| Paper | Why it matters to you | DOI |
|---|---|---|
| Football-specific validity of TRACAB's optical video tracking (PLoS ONE, 2020) | A published multi-camera optical system validated against ground truth. Directly relevant to how you frame accuracy expectations. | `10.1371/journal.pone.0230179` |
| Pose2Sim: markerless sports kinematics, accuracy (Sensors, 2021) | What markerless accuracy looks like when measured honestly. | `10.3390/s21196530` |
| A Review of the Evolution of Vision-Based Motion Analysis in sport (Sports Med Open, 2018) | Framing for the introduction. | `10.1186/s40798-018-0139-y` |
| Automated Service Height Fault Detection Using Computer Vision (Sensors, 2023) | Another rule-adjudication-by-camera system, badminton. Good comparison for your "coaching not officiating" positioning. | `10.3390/s23249759` |

## What this does not fix

Fourteen good additions takes you to roughly 28, which is respectable. It does not address the
deeper gap: your Related Work has no engagement with the table-tennis and badminton tracking
literature, which is the closest published work to what you built and which reports accuracy
numbers you could be compared against. Reading four or five of the papers above and writing one
honest paragraph placing PocketDRS among them would strengthen the paper more than the citation
count does.
