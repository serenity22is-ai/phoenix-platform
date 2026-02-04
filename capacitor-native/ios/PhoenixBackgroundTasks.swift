/**
 * PHOENIX iOS Background Tasks (Build #91)
 *
 * Registers BGAppRefreshTask for periodic node heartbeat when the app
 * is backgrounded. iOS allows ~30s of execution every ~15 minutes.
 *
 * After running `npx cap add ios`, integrate this into:
 *   ios/App/App/AppDelegate.swift
 *
 * Required Info.plist additions (see SETUP section below).
 */

import UIKit
import BackgroundTasks

// MARK: - Background Task Identifiers
let HEARTBEAT_TASK_ID = "com.phoenix.app.nodeHeartbeat"
let FLUSH_TASK_ID = "com.phoenix.app.nodeFlush"

// MARK: - PhoenixBackgroundTasks

class PhoenixBackgroundTasks {

    /// Server URL for heartbeat/flush (set from JS bridge or config)
    static var serverURL: String = ""
    /// Helper token for authentication
    static var helperToken: String = ""
    /// Node ID from authentication
    static var nodeId: String = ""

    // MARK: Register tasks

    /// Call this from AppDelegate.didFinishLaunchingWithOptions
    static func registerBackgroundTasks() {
        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: HEARTBEAT_TASK_ID,
            using: nil
        ) { task in
            handleHeartbeatTask(task: task as! BGAppRefreshTask)
        }

        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: FLUSH_TASK_ID,
            using: nil
        ) { task in
            handleFlushTask(task: task as! BGProcessingTask)
        }

        print("[PhoenixBG] Background tasks registered")
    }

    // MARK: Schedule tasks

    /// Call this when the app enters background
    static func scheduleHeartbeat() {
        let request = BGAppRefreshTaskRequest(identifier: HEARTBEAT_TASK_ID)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60) // 15 minutes

        do {
            try BGTaskScheduler.shared.submit(request)
            print("[PhoenixBG] Heartbeat task scheduled")
        } catch {
            print("[PhoenixBG] Failed to schedule heartbeat: \(error)")
        }
    }

    static func scheduleFlush() {
        let request = BGProcessingTaskRequest(identifier: FLUSH_TASK_ID)
        request.requiresNetworkConnectivity = true
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)

        do {
            try BGTaskScheduler.shared.submit(request)
            print("[PhoenixBG] Flush task scheduled")
        } catch {
            print("[PhoenixBG] Failed to schedule flush: \(error)")
        }
    }

    // MARK: Handle tasks

    private static func handleHeartbeatTask(task: BGAppRefreshTask) {
        // Schedule the next heartbeat immediately
        scheduleHeartbeat()

        guard !serverURL.isEmpty, !helperToken.isEmpty, !nodeId.isEmpty else {
            print("[PhoenixBG] Missing config — skipping heartbeat")
            task.setTaskCompleted(success: false)
            return
        }

        // Set expiration handler
        task.expirationHandler = {
            print("[PhoenixBG] Heartbeat task expired")
        }

        // Send heartbeat via URLSession
        let url = URL(string: "\(serverURL)/api/v1/node/heartbeat")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(helperToken, forHTTPHeaderField: "X-Helper-Token")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("PhoenixNodeClient/1.0.0 (ios-bg)", forHTTPHeaderField: "User-Agent")

        let payload: [String: Any] = [
            "node_id": nodeId,
            "uptime_s": 0,
            "events_buffered": 0,
            "version": "1.0.0",
            "node_type": "ios"
        ]

        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)

        let session = URLSession(configuration: .default)
        let dataTask = session.dataTask(with: request) { data, response, error in
            if let error = error {
                print("[PhoenixBG] Heartbeat failed: \(error.localizedDescription)")
                task.setTaskCompleted(success: false)
                return
            }

            if let httpResponse = response as? HTTPURLResponse {
                print("[PhoenixBG] Heartbeat response: \(httpResponse.statusCode)")
                task.setTaskCompleted(success: httpResponse.statusCode == 200)
            } else {
                task.setTaskCompleted(success: false)
            }
        }
        dataTask.resume()
    }

    private static func handleFlushTask(task: BGProcessingTask) {
        // Schedule next flush
        scheduleFlush()

        // For now, the WebView JS handles the actual event buffer.
        // This task is a placeholder for future native event buffering.
        // The heartbeat task is the critical one for maintaining node status.
        print("[PhoenixBG] Flush task running (delegated to WebView)")
        task.setTaskCompleted(success: true)
    }

    // MARK: Configuration

    /// Called from JavaScript bridge to set credentials for background tasks
    static func configure(serverURL: String, helperToken: String, nodeId: String) {
        self.serverURL = serverURL
        self.helperToken = helperToken
        self.nodeId = nodeId
        print("[PhoenixBG] Configured: server=\(serverURL), node=\(nodeId)")
    }
}


/*
 * =========================================================================
 * SETUP — AppDelegate.swift integration
 * =========================================================================
 *
 * After `npx cap add ios`, modify ios/App/App/AppDelegate.swift:
 *
 * 1. In didFinishLaunchingWithOptions:
 *
 *    PhoenixBackgroundTasks.registerBackgroundTasks()
 *
 * 2. Add applicationDidEnterBackground method (or in sceneDidEnterBackground):
 *
 *    func applicationDidEnterBackground(_ application: UIApplication) {
 *        PhoenixBackgroundTasks.scheduleHeartbeat()
 *        PhoenixBackgroundTasks.scheduleFlush()
 *    }
 *
 * =========================================================================
 * SETUP — Info.plist additions
 * =========================================================================
 *
 * Add to ios/App/App/Info.plist:
 *
 *    <key>BGTaskSchedulerPermittedIdentifiers</key>
 *    <array>
 *        <string>com.phoenix.app.nodeHeartbeat</string>
 *        <string>com.phoenix.app.nodeFlush</string>
 *    </array>
 *    <key>UIBackgroundModes</key>
 *    <array>
 *        <string>fetch</string>
 *        <string>processing</string>
 *    </array>
 *
 * =========================================================================
 */
