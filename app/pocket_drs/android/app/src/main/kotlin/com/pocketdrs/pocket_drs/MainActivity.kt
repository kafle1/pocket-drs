package com.pocketdrs.pocket_drs

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.media.MediaMuxer
import android.os.Handler
import android.os.Looper
import android.os.StatFs
import android.view.KeyEvent
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.nio.ByteBuffer
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
                        val input = call.argument<String>("input")!!
                        val output = call.argument<String>("output")!!
                        val startUs = call.argument<Int>("startMs")!! * 1000L
                        val endUs = call.argument<Int>("endMs")!! * 1000L
                        val main = Handler(Looper.getMainLooper())
                        thread {
                            try {
                                val span = trim(input, output, startUs, endUs)
                                main.post { result.success(span) }
                            } catch (e: Exception) {
                                File(output).delete()
                                main.post { result.error("trim", e.message ?: e.toString(), null) }
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

    /** Copies the video track around [startUs]..[endUs] without re-encoding; returns where that window sits in the clip, in ms. */
    private fun trim(input: String, output: String, startUs: Long, endUs: Long): List<Int> {
        val retriever = MediaMetadataRetriever()
        val rotation = try {
            retriever.setDataSource(input)
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION)?.toInt() ?: 0
        } finally {
            retriever.release()
        }
        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(input)
            val track = (0 until extractor.trackCount).firstOrNull {
                extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true
            } ?: throw IllegalStateException("The recording has no video.")
            val format = extractor.getTrackFormat(track)
            extractor.selectTrack(track)
            // the clip has to open on a keyframe, and the next one can be a second into the delivery
            extractor.seekTo(startUs, MediaExtractor.SEEK_TO_PREVIOUS_SYNC)
            // gallery trims keep the frames before the cut at negative times, so only a missing sample means the end
            if (extractor.sampleTrackIndex < 0 || extractor.sampleTime > endUs) throw IllegalStateException("The clip is too short.")
            val first = extractor.sampleTime
            var last = first
            val muxer = MediaMuxer(output, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            try {
                muxer.setOrientationHint(rotation)
                val out = muxer.addTrack(format)
                muxer.start()
                val size = if (format.containsKey(MediaFormat.KEY_MAX_INPUT_SIZE)) format.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE) else 4 shl 20
                val buffer = ByteBuffer.allocate(size)
                val info = MediaCodec.BufferInfo()
                while (extractor.sampleTrackIndex >= 0) {
                    val t = extractor.sampleTime
                    if (t > endUs) break
                    val n = extractor.readSampleData(buffer, 0)
                    if (n < 0) break
                    val key = (extractor.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC) != 0
                    info.set(0, n, t - first, if (key) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0)
                    muxer.writeSampleData(out, buffer, info)
                    last = t
                    extractor.advance()
                }
                muxer.stop()
            } finally {
                muxer.release()
            }
            val startMs = (startUs - first).coerceAtLeast(0L) / 1000
            // rounded up so the server's inclusive segment still reaches the last frame
            return listOf(startMs.toInt(), maxOf(startMs + 1, (last - first + 999) / 1000).toInt())
        } finally {
            extractor.release()
        }
    }
}
