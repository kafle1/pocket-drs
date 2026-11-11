package com.pocketdrs.pocket_drs

import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.StatFs
import android.provider.Settings
import android.view.KeyEvent
import android.view.WindowManager
import androidx.annotation.OptIn
import androidx.media3.common.Effect
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi
import androidx.media3.effect.Presentation
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.Transformer
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import kotlin.concurrent.thread

class MainActivity : FlutterActivity() {
    private var channel: MethodChannel? = null
    // a running session is the only time the screen is held on, so the same flag gates volume keys
    private var session = false

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "pocket_drs/native").apply {
            setMethodCallHandler { call, result ->
                when (call.method) {
                    "trim" -> {
                        trim(
                            call.argument<String>("input")!!,
                            call.argument<String>("output")!!,
                            call.argument<Int>("startMs")!!.toLong(),
                            call.argument<Int>("endMs")!!.toLong(),
                            result,
                        )
                    }
                    "videoInfo" -> {
                        val path = call.argument<String>("path")!!
                        val main = Handler(Looper.getMainLooper())
                        thread {
                            try {
                                val info = videoInfo(path)
                                main.post { result.success(info) }
                            } catch (e: Exception) {
                                main.post { result.error("videoInfo", e.message ?: e.toString(), null) }
                            }
                        }
                    }
                    "keepScreenOn" -> {
                        session = call.arguments as Boolean
                        if (session) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                        result.success(null)
                    }
                    "freeBytes" -> result.success(StatFs(cacheDir.path).availableBytes)
                    // survives a reinstall, so free reviews count per phone
                    "deviceId" -> result.success(Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID))
                    else -> result.notImplemented()
                }
            }
        }
    }

    // bluetooth shutters arrive as volume keys too
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (session && (event.keyCode == KeyEvent.KEYCODE_VOLUME_UP || event.keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)) {
            if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) channel?.invokeMethod("mark", null)
            return true
        }
        return super.dispatchKeyEvent(event)
    }

    /** The clip's frame rate (0 when the file doesn't say) and length in ms. */
    private fun videoInfo(path: String): Map<String, Any> {
        val retriever = MediaMetadataRetriever()
        val (durationMs, frames) = try {
            retriever.setDataSource(path)
            val ms = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
            val n = if (Build.VERSION.SDK_INT >= 28)
                retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_FRAME_COUNT)?.toLongOrNull() else null
            ms to n
        } finally {
            retriever.release()
        }
        val extractor = MediaExtractor()
        val declared = try {
            extractor.setDataSource(path)
            (0 until extractor.trackCount).map { extractor.getTrackFormat(it) }
                .firstOrNull { it.getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true }
                ?.takeIf { it.containsKey(MediaFormat.KEY_FRAME_RATE) }
                // stored as an int by most muxers, a float by some
                ?.let { f ->
                    try { f.getInteger(MediaFormat.KEY_FRAME_RATE).toDouble() }
                    catch (e: ClassCastException) { f.getFloat(MediaFormat.KEY_FRAME_RATE).toDouble() }
                }
        } finally {
            extractor.release()
        }
        // phones write a nominal rate that can be wrong for variable-rate video, so the counted rate wins
        val counted = if (frames != null && durationMs > 0) frames * 1000.0 / durationMs else null
        return mapOf("fps" to (counted ?: declared ?: 0.0), "durationMs" to durationMs)
    }

    /** Re-encodes [startMs]..[endMs] as silent H.264 with a 720 px short side at the source frame rate; replies with where that window sits in the clip, in ms. */
    @OptIn(UnstableApi::class)
    private fun trim(input: String, output: String, startMs: Long, endMs: Long, result: MethodChannel.Result) {
        val main = Handler(Looper.getMainLooper())
        val fail: (String) -> Unit = { message ->
            File(output).delete()
            main.post { result.error("trim", message, null) }
        }
        thread {
            val shortSide = try {
                val retriever = MediaMetadataRetriever()
                try {
                    retriever.setDataSource(input)
                    val duration = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull()
                    if (endMs <= startMs || (duration != null && startMs >= duration)) return@thread fail("The clip is too short.")
                    val w = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull() ?: 0
                    val h = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull() ?: 0
                    if (w <= 0 || h <= 0) return@thread fail("The recording has no video.")
                    minOf(w, h)
                } finally {
                    retriever.release()
                }
            } catch (e: Exception) {
                return@thread fail(e.message ?: e.toString())
            }
            // transformer has to be built and driven from a looper thread
            main.post {
                try {
                    val item = MediaItem.Builder()
                        .setUri(Uri.fromFile(File(input)))
                        .setClippingConfiguration(
                            MediaItem.ClippingConfiguration.Builder().setStartPositionMs(startMs).setEndPositionMs(endMs).build()
                        )
                        .build()
                    // short side, not height, so portrait and landscape both land on 720
                    val effects = if (shortSide > 720) listOf<Effect>(Presentation.createForShortSide(720)) else emptyList()
                    val edited = EditedMediaItem.Builder(item)
                        .setRemoveAudio(true)
                        .setEffects(Effects(emptyList(), effects))
                        .build()
                    Transformer.Builder(applicationContext)
                        .setVideoMimeType(MimeTypes.VIDEO_H264)
                        .addListener(object : Transformer.Listener {
                            override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                                if (exportResult.videoFrameCount == 0) return fail("The clip is too short.")
                                val ms = if (exportResult.durationMs > 0) exportResult.durationMs else endMs - startMs
                                result.success(listOf(0, maxOf(1L, ms).toInt()))
                            }

                            override fun onError(composition: Composition, exportResult: ExportResult, exportException: ExportException) {
                                fail(exportException.message ?: exportException.toString())
                            }
                        })
                        .build()
                        .start(edited, output)
                } catch (e: Exception) {
                    fail(e.message ?: e.toString())
                }
            }
        }
    }
}
