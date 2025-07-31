#!/bin/bash
date -s "$(curl -s 'https://timeapi.io/api/Time/current/zone?timeZone=Asia/Ho_Chi_Minh' | jq -r .dateTime | cut -d '.' -f1 | sed 's/T/ /')"
