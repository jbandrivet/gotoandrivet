#pragma once
#include "../arduino_shim.h"
struct BancGpsVal { bool isValid() const { return false; } bool isUpdated() const { return false; }
  double lat() const { return 0; } double lng() const { return 0; }
  int year() const { return 2026; } int month() const { return 1; } int day() const { return 1; }
  int hour() const { return 0; } int minute() const { return 0; } int second() const { return 0; } };
struct TinyGPSPlus { BancGpsVal location, date, time; bool encode(char) { return false; } };
