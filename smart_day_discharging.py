import appdaemon.plugins.hass.hassapi as hass
import datetime

    # This app triggers non sequential discharging during day hours if price condition is met.

class SmartDayDischarging(hass.Hass):
    def initialize(self):
        """Initialize the app and set up the routines for regular updates."""
        # Define sensor names
        self.sensor_name = "sensor.nordpool_kwh_se3_sek_3_10_025"  # Nordpool sensor for prices
        self.mean_price_sensor = "sensor.selected_charging_hours_prices"  # Mean price sensor
        self.output_selected_hours = "sensor.selected_discharging_hours"
        self.output_prices_for_selected_hours = "sensor.selected_discharging_hours_prices"

        # Trigger the update calculation every day at 02:00
        self.run_daily(self.update_discharging_hours, datetime.time(2, 0))
        # Run the calculation once at startup
        self.update_discharging_hours()

    def update_discharging_hours(self, *args):
        """Update the discharging hours based on the 7 most expensive hours."""
        # Clear previous state and attributes of selected_discharging_hours
        self.set_state(self.output_selected_hours, state="unknown", attributes={})
        self.set_state(self.output_prices_for_selected_hours, state="unknown", attributes={})

        # Fetch today's prices from the Nordpool sensor (hourly prices for today)
        today_prices = self.get_state(self.sensor_name, attribute="today") or []
        if not today_prices or len(today_prices) != 24:
            self.log("Error: Not enough data for price calculation")
            return

        # Only consider the hours between 7:00 and 21:00 (indices 7 to 22)
        filtered_prices = today_prices[7:23]  # hours 7 to 21 (inclusive)

        # Sort the hours by price (descending) and select the top 7 most expensive hours
        sorted_hours = sorted(
            [(i + 7, price) for i, price in enumerate(filtered_prices) if price is not None],
            key=lambda x: x[1],
            reverse=True
        )
        self.log(f"Sorted hours (7-22) by price (descending): {sorted_hours}")

        # Select the 7 most expensive hours
        most_expensive_7 = sorted_hours[:7]
        self.log(f"Selected 7 most expensive hours: {most_expensive_7}")

        # Calculate the mean price of the 7 most expensive hours
        mean_7_expensive = sum(price for _, price in most_expensive_7) / len(most_expensive_7)
        self.log(f"Calculated mean price for 7 most expensive hours: {mean_7_expensive:.2f}")

        # Fetch the value of sensor.selected_charging_hours_prices
        mean_price_value = float(self.get_state(self.mean_price_sensor, state=None) or 0)

        # If the mean_price_value is 0, use the value from sensor.chosen_3_hours instead
        if mean_price_value == 0:
            mean_price_value = float(self.get_state('sensor.mock_chosen_3_hours', state=None) or 0)
            self.log(f"Using value from sensor.mock_chosen_3_hours: {mean_price_value:.2f}")
        else:
            self.log(f"Mean night charging price: {mean_price_value:.2f}")

        # Calculate the price difference
        price_difference = mean_7_expensive - mean_price_value
        self.log(f"Price difference: {price_difference:.2f}")


        if price_difference > 40: # CHANGEME
            self.log("Price difference is greater than 40 öre, scheduling discharging.")
            self.log_to_logbook("Price difference is greater than 40 öre, scheduling discharging.")
            # Proceed with scheduling discharging
            selected_hours = [hour for hour, _ in most_expensive_7]
            selected_hours.sort()  # Ensure hours are sorted in order

            # Format the time range string for selected hours
            time_range_str = self.split_into_ranges(selected_hours)
            self.log(f"Today's selected time range for discharging: {time_range_str}")
            self.set_state(self.output_selected_hours, state=f"{time_range_str} | Mean: {mean_7_expensive:.2f}",
                attributes={"selected_hours": selected_hours, "mean_price_for_selected_hours": mean_7_expensive})

            # Update the new sensor for the mean price of the selected hours
            self.set_state(self.output_prices_for_selected_hours, state=f"{mean_7_expensive:.2f}",
                attributes={"mean_price_for_selected_hours": mean_7_expensive})

            # Schedule discharging for the selected hours
            self.schedule_discharging(selected_hours)
        else:
            self.log("Price difference is too low, discharging will not be scheduled.")
            self.log_to_logbook("Price difference is too low, discharging will not be scheduled.")
            self.set_state(self.output_selected_hours, state="Price difference too low")
            self.set_state(self.output_prices_for_selected_hours, state="Price difference too low")

    def split_into_ranges(self, selected_hours):
        """Split selected hours into continuous ranges and output as start-end format."""
        ranges = self.group_sequential_hours(selected_hours)
        
        # Format each group of hours into a readable string
        formatted_ranges = []
        for r in ranges:
            start_hour = r[0]
            end_hour = r[-1]
            formatted_ranges.append(f"{start_hour:02}:00-{end_hour + 1:02}:00")
        
        return ", ".join(formatted_ranges)

    def group_sequential_hours(self, selected_hours):
        """Groups consecutive hours into continuous blocks."""
        ranges = []
        current_range = [selected_hours[0]]  # Start with the first hour

        for i in range(1, len(selected_hours)):
            # If current hour is consecutive to the previous one, add it to the current range
            if selected_hours[i] == selected_hours[i - 1] + 1:
                current_range.append(selected_hours[i])
            else:
                # If not consecutive, push the current range and start a new one
                ranges.append(current_range)
                current_range = [selected_hours[i]]

        # Don't forget to add the last range
        ranges.append(current_range)
        
        return ranges

    def schedule_discharging(self, selected_hours):
        """Schedule discharging for the selected hours, preventing stop if following hour is part of the sequence."""
        now = self.datetime()  # Get the current datetime object for logging
        today_date = now.date()  # Get today's date

        # Group selected hours into continuous ranges (sequences of hours)
        ranges = self.group_sequential_hours(selected_hours)

        # Loop through the ranges and schedule start and stop times for discharging
        for r in ranges:
            start_hour = r[0]  # First hour of the range
            end_hour = r[-1]  # Last hour of the range
            
            # Schedule the start time (at the start of the range)
            start_time = datetime.datetime.combine(today_date, datetime.time(start_hour, 0))
            self.log(f"Scheduling start discharging at {start_time}")
            self.run_at(self.start_discharging, start_time)
            
            # Schedule the stop time (at the last hour + 1, since discharging needs to stop after the last hour)
            stop_time = datetime.datetime.combine(today_date, datetime.time((end_hour + 1) % 24, 0))
            self.log(f"Scheduling stop discharging at {stop_time}")
            self.run_at(self.stop_discharging, stop_time)

        # Log the ranges to the logbook
        self.log_to_logbook(f"Discharging scheduled for the following time ranges: {ranges}")

    def start_discharging(self, kwargs):
        """Start discharging the battery only if current time is within selected hours."""
        now = self.datetime()  # Get the current datetime object for validation
        
        # Fetch today's dynamic range for discharging
        selected_hours_str = self.get_state(self.output_selected_hours, state=None)
        if selected_hours_str:
            # Parse the selected hours into a list
            selected_hours = [int(h.split(':')[0]) for h in selected_hours_str.split(',')]  # Assuming format: "15:00,17:00,19:00"
        else:
            # If no dynamic range is set, log an error and do not trigger discharging
            self.log(f"Error: No dynamic discharging range found for today. Discharging will not be triggered.")
            self.log_to_logbook("Error: No dynamic discharging range found for today. Discharging will not be triggered.")
            return  # Exit, do not trigger discharging

        # Ensure the current time is within the selected range for today (non-sequential hours)
        current_hour = now.hour

        # Check if the current hour is one of the selected discharging hours
        if current_hour in selected_hours:
            # Proceed with discharging
            self.log_to_logbook(f"Starting battery discharging")
            self.run_in(self.set_self_consumption_mode, 2)  # Start discharging after 2 seconds delay
            self.call_service(
                "input_select/select_option",
                entity_id="input_select.set_sg_battery_forced_charge_discharge_cmd",
                option="Stop (default)"  # Start discharging action
            )
        else:
            # Log that the discharging attempt was outside the selected hours
            self.log(f"Discharging triggered at but current hour {current_hour} is outside of the selected hours ({selected_hours}).")
            self.log_to_logbook(f"Discharging attempt outside of selected hours ({selected_hours}).")


    def stop_discharging(self, kwargs):
        """Stop discharging the battery."""
        self.log_to_logbook(f"Stopping battery discharging.")
        self.run_in(self.set_forced_mode, 2)
        self.call_service(
            "input_select/select_option",
            entity_id="input_select.set_sg_battery_forced_charge_discharge_cmd",
            option="Stop (default)"
        )

    def set_self_consumption_mode(self, kwargs):
        """Set EMS mode to Self consumption (default)."""
        self.log_to_logbook("Setting EMS mode to Self consumption (default).")
        self.call_service(
            "input_select/select_option",
            entity_id="input_select.set_sg_ems_mode",
            option="Self-consumption mode (default)"
        )

    def set_forced_mode(self, kwargs):
        """Set EMS mode to Forced mode."""
        self.log_to_logbook("Setting EMS mode to Forced mode.")
        self.call_service(
            "input_select/select_option",
            entity_id="input_select.set_sg_ems_mode",
            option="Forced mode"
        )

    def log_to_logbook(self, message):
        """Logs a message to the Home Assistant Logbook."""
        self.call_service(
            "logbook/log",
            name="Smart day discharge",
            message=message,
            entity_id="sensor.selected_discharging_hours"  
        )

