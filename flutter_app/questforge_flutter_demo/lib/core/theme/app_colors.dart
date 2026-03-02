// lib/core/theme/app_colors.dart
import 'package:flutter/material.dart';

/// QuestForge UI Color System
/// - brand colors (Primary / Secondary / Accent)
/// - surfaces, text, feedback colors
/// - theme builder (ThemeData)
///
/// Naming rules:
/// - "Primary" = main brand blue
/// - "Secondary" = warm orange
/// - "Accent" = fresh green
@immutable
class AppColors {
  const AppColors._();

  // -----------------------------
  // Brand Palette
  // -----------------------------
  static const Color primary = Color(0xFF2F7BFF);
  static const Color primaryDark = Color(0xFF1E4FD6);
  static const Color primarySoft = Color(0xFFBFD7FF);

  static const Color secondary = Color(0xFFFFA43A);
  static const Color secondaryDark = Color(0xFFE07B00);
  static const Color secondarySoft = Color(0xFFFFE0B7);

  static const Color accent = Color(0xFF39D98A);
  static const Color accentDark = Color(0xFF1FAE66);
  static const Color accentSoft = Color(0xFFC9F5E1);

  // -----------------------------
  // Surfaces / Background
  // -----------------------------
  static const Color background = Color(0xFFFFF8EE); // paper-like warm
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceAlt = Color(0xFFF3F7FF);

  static const Color border = Color(0xFFE6EAF2);

  // -----------------------------
  // Text
  // -----------------------------
  static const Color textPrimary = Color(0xFF1C2430);
  static const Color textSecondary = Color(0xFF5E6B7A);
  static const Color textTertiary = Color(0xFF92A0B2);

  static const Color textOnDark = Color(0xFFFFFFFF);

  // -----------------------------
  // Feedback
  // -----------------------------
  static const Color success = Color(0xFF2ECC71);
  static const Color warning = Color(0xFFFFB020);
  static const Color error = Color(0xFFFF4D4F);
  static const Color info = primary;

  // -----------------------------
  // Disabled
  // -----------------------------
  static const Color disabledBg = border;
  static const Color disabledText = textTertiary;

  // -----------------------------
  // Helpers
  // -----------------------------
  static Color withOpacity(Color c, double opacity) => c.withOpacity(opacity);
}

/// Standard theme for QuestForge.
/// You can use:
///   theme: AppTheme.light()
@immutable
class AppTheme {
  const AppTheme._();

  static ThemeData light() {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      brightness: Brightness.light,
      primary: AppColors.primary,
      secondary: AppColors.secondary,
      surface: AppColors.surface,
      background: AppColors.background,
      error: AppColors.error,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: AppColors.background,

      // Typography (you can later plug in a custom font)
      textTheme: const TextTheme(
        titleLarge: TextStyle(
          color: AppColors.textPrimary,
          fontWeight: FontWeight.w800,
          fontSize: 22,
        ),
        titleMedium: TextStyle(
          color: AppColors.textPrimary,
          fontWeight: FontWeight.w700,
          fontSize: 18,
        ),
        bodyLarge: TextStyle(
          color: AppColors.textPrimary,
          fontSize: 16,
        ),
        bodyMedium: TextStyle(
          color: AppColors.textSecondary,
          fontSize: 14,
        ),
        bodySmall: TextStyle(
          color: AppColors.textTertiary,
          fontSize: 12,
        ),
      ),

      // Divider / Borders
      dividerColor: AppColors.border,

      // AppBar
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        foregroundColor: AppColors.textPrimary,
        centerTitle: true,
      ),

      // Cards
      cardTheme: CardThemeData(
        color: AppColors.surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: AppColors.border),
        ),
      ),

      // Buttons
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: _elevatedBase(
          bg: AppColors.primary,
          pressedBg: AppColors.primaryDark,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: _outlinedBase(
          border: AppColors.primary,
          pressedOverlay: AppColors.primary.withOpacity(0.10),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppColors.primary,
          textStyle: const TextStyle(fontWeight: FontWeight.w700),
        ),
      ),

      // Inputs
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surface,
        hintStyle: const TextStyle(color: AppColors.textTertiary),
        labelStyle: const TextStyle(color: AppColors.textSecondary),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: AppColors.primary, width: 2),
        ),
      ),
    );
  }

  // -------------------------------------------
  // Button style presets you can reuse anywhere
  // -------------------------------------------

  /// Primary / Secondary / Tertiary buttons
  static ButtonStyle elevatedPrimary() => _elevatedBase(
        bg: AppColors.primary,
        pressedBg: AppColors.primaryDark,
      );

  static ButtonStyle elevatedSecondary() => _elevatedBase(
        bg: AppColors.secondary,
        pressedBg: AppColors.secondaryDark,
      );

  static ButtonStyle elevatedTertiary() => _elevatedBase(
        bg: AppColors.accent,
        pressedBg: AppColors.accentDark,
      );

  /// "Glass" overlay style (for your semi-transparent button PNG style)
  /// Use it for containers behind text/buttons placed on top of background art.
  static BoxDecoration glassDecoration({
    required Color brandColor,
    double fillOpacity = 0.18,
    double borderOpacity = 0.65,
    double shadowOpacity = 0.12,
    double radius = 22,
  }) {
    return BoxDecoration(
      color: brandColor.withOpacity(fillOpacity),
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(
        color: brandColor.withOpacity(borderOpacity),
        width: 2,
      ),
      boxShadow: [
        BoxShadow(
          color: Colors.black.withOpacity(shadowOpacity),
          blurRadius: 18,
          offset: const Offset(0, 10),
        ),
      ],
    );
  }

  // -----------------------------
  // Internal style builders
  // -----------------------------
  static ButtonStyle _elevatedBase({
    required Color bg,
    required Color pressedBg,
  }) {
    return ButtonStyle(
      backgroundColor: MaterialStateProperty.resolveWith((states) {
        if (states.contains(MaterialState.disabled))
          return AppColors.disabledBg;
        if (states.contains(MaterialState.pressed)) return pressedBg;
        return bg;
      }),
      foregroundColor: MaterialStateProperty.resolveWith((states) {
        if (states.contains(MaterialState.disabled))
          return AppColors.disabledText;
        return AppColors.textOnDark;
      }),
      textStyle: MaterialStateProperty.all(
        const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
      ),
      padding: MaterialStateProperty.all(
        const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      ),
      shape: MaterialStateProperty.all(
        RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
      elevation: MaterialStateProperty.all(0),
    );
  }

  static ButtonStyle _outlinedBase({
    required Color border,
    required Color pressedOverlay,
  }) {
    return ButtonStyle(
      foregroundColor: MaterialStateProperty.resolveWith((states) {
        if (states.contains(MaterialState.disabled))
          return AppColors.disabledText;
        return border;
      }),
      side: MaterialStateProperty.resolveWith((states) {
        if (states.contains(MaterialState.disabled)) {
          return const BorderSide(color: AppColors.border);
        }
        return BorderSide(color: border, width: 2);
      }),
      overlayColor: MaterialStateProperty.all(pressedOverlay),
      textStyle: MaterialStateProperty.all(
        const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
      ),
      padding: MaterialStateProperty.all(
        const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      ),
      shape: MaterialStateProperty.all(
        RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
    );
  }
}
