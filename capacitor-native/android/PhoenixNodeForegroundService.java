/**
 * PHOENIX Node Foreground Service (Build #91)
 *
 * Android foreground service that keeps the Phoenix node client alive
 * when the app is backgrounded. Shows a persistent notification to comply
 * with Android's background execution requirements.
 *
 * After running `npx cap add android`, copy this file to:
 *   android/app/src/main/java/com/phoenix/app/PhoenixNodeForegroundService.java
 *
 * Required AndroidManifest.xml additions (see SETUP section below).
 */

package com.phoenix.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

public class PhoenixNodeForegroundService extends Service {

    private static final String CHANNEL_ID = "phoenix_node_channel";
    private static final String CHANNEL_NAME = "Phoenix Node Service";
    private static final int NOTIFICATION_ID = 9001;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Build the persistent notification
        Intent notificationIntent = new Intent(this, MainActivity.class);
        notificationIntent.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);

        PendingIntent pendingIntent = PendingIntent.getActivity(
            this, 0, notificationIntent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        Notification notification = new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Phoenix Node Active")
            .setContentText("Earning rewards \u2014 your node is contributing to the network")
            .setSmallIcon(android.R.drawable.ic_menu_manage)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build();

        startForeground(NOTIFICATION_ID, notification);

        // If the system kills the service, restart it
        return START_STICKY;
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                CHANNEL_NAME,
                NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Keeps the Phoenix node running in the background");
            channel.setShowBadge(false);

            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
    }
}


/*
 * =========================================================================
 * SETUP — AndroidManifest.xml additions
 * =========================================================================
 *
 * After `npx cap add android`, add these to
 * android/app/src/main/AndroidManifest.xml:
 *
 * 1. Inside <manifest> (before <application>):
 *
 *    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
 *    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" />
 *    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
 *
 * 2. Inside <application> (alongside <activity>):
 *
 *    <service
 *        android:name=".PhoenixNodeForegroundService"
 *        android:enabled="true"
 *        android:exported="false"
 *        android:foregroundServiceType="dataSync" />
 *
 * =========================================================================
 */
