# Pocket DRS walkthrough

A short tour of each screen in the app. For step-by-step instructions, see the
[user guide](GUIDE.md).

[![App walkthrough: tap to play the video](media/app-walkthrough.jpg)](media/app-walkthrough.mp4)

## Home screen

The screen you land on when you open the app. The title reads "Pocket DRS", with the line "Check
leg before wicket calls from your phone." underneath.

![Home screen](../app/pocket_drs/fastlane/metadata/android/en-US/images/phoneScreenshots/4_home.png)

Two cards open the app's two flows:

- **Start a session** opens the camera to record and check deliveries one after another.
- **Analyse a video** opens a flow to check one clip you already have.

Below the cards, a "For a good read" tip list reminds you to put the tripod behind the bowler's
stumps, keep both sets of stumps in frame, use a red or pink ball, film in good daylight, and set
the pitch length in Settings if you're on a shorter pitch. The gear icon in the top corner opens
Settings.

## Start a session screen

Opens the phone's camera for filming deliveries one after another. Before you mark the stumps, a
message tells you to stand the phone behind the bowler's stumps with both sets of stumps in view,
then tap **Mark stumps**.

Tapping **Mark stumps** switches to the stump-marking view, the same eight-tap marking used by
Analyse a video (see below). Once all eight marks are placed and you tap **Continue**, you choose
the batter's handedness with a **Right-handed** / **Left-handed** switch, and the screen is ready
to record.

![Marking the stumps](../app/pocket_drs/fastlane/metadata/android/en-US/images/phoneScreenshots/3_stumps.png)

From here, the message changes to tell you to press **Ball**, or a volume key, right after each
delivery. Each tap cuts the last four seconds of video and sends it off. A list of cards below
shows each ball's progress and, once ready, its result: **Out**, **Not out**, **Umpire's call**,
or **No LBW call**. Swipe a card away to remove it. Tapping a card opens its full result, with a
**Back to session** button to return.

Trying to leave partway through asks **Leave session?**, warning that the results there will be
lost, with **Stay** and **Leave** buttons.

## Analyse a video screen

Walks through checking one saved or newly recorded clip, in four steps: **Choose a video**,
**Trim to the delivery**, **Pick a clear frame**, and **Mark the stumps**, followed by
**Analysing** and the **Result**.

**Choose a video.** Buttons let you **Record video** now or **Choose from phone** to pick an
existing clip. A **Right-handed** / **Left-handed** switch sets the batter's handedness.

**Trim to the delivery.** Two handles on a timeline mark the start and end of the part to check.
Drag them to the delivery, then tap **Use this part**. At least 0.2 seconds must be selected.

**Pick a clear frame.** Scrub through the trimmed clip, or step forward and back in tenths of a
second, to land on a sharp frame, then tap **Use this frame**.

**Mark the stumps.** The same eight-tap marking as the session screen: batter's stumps top left,
top right, bottom right, bottom left, then bowler's stumps in the same order.

**Analysing.** A progress view shows what the server is doing: loading the video, reading your
stump marks, finding the ball in every frame, working out the ball's path, making the LBW call,
and finishing up.

**Result.** The shared result view: the video with the ball's path drawn over it, a verdict banner
if one was reached, speed, swing, and spin tiles, and, only when there's a verdict, a **View in
3D** button. A **Check another ball** button restarts the flow from the first step.

![Result screen](../app/pocket_drs/fastlane/metadata/android/en-US/images/phoneScreenshots/1_result.png)
![The 3D view](../app/pocket_drs/fastlane/metadata/android/en-US/images/phoneScreenshots/2_3d.png)

## Settings screen

Reached from the gear icon on the home screen.

![Settings screen](../app/pocket_drs/fastlane/metadata/android/en-US/images/phoneScreenshots/5_settings.png)

- **Appearance**: a **System** / **Light** / **Dark** switch for the app's theme.
- **Units**: a **km/h** / **mph** switch for how speed is shown.
- **Pitch**: the pitch length used to scale speed and the 3D view, editable from 10 to 25 metres,
  with a **Full size** shortcut for a standard 20.12 metre pitch.
- **Storage** (on phones only): a switch to delete clips you record in the app once you leave the
  result screen.
- **About**: the app version, a **Source code** link to the project on GitHub, and a **Privacy
  policy** link.
