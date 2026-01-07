"""
Generate test audio files using Edge TTS for E2E testing.

This script generates sample audio files that can be used as input
for testing the voice agent backend.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lib.voice_streaming_framework.tts.factory import get_tts_provider
from lib.voice_streaming_framework.tts.base import TTSConfig


async def generate_test_audio():
    """Generate test audio files for E2E testing."""

    # Output directory
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixtures_dir.mkdir(exist_ok=True)

    # Test phrases in different languages
    test_cases = [
        {
            "text": "你好，今天天气怎么样？",
            "voice": "zh-CN-XiaoxiaoNeural",
            "filename": "test_hello_chinese.mp3",
            "description": "Chinese greeting asking about weather"
        },
        {
            "text": "Hello, how are you today?",
            "voice": "en-US-AriaNeural",
            "filename": "test_hello_english.mp3",
            "description": "English greeting"
        },
        {
            "text": "请帮我查询明天的日程安排。",
            "voice": "zh-CN-XiaoxiaoNeural",
            "filename": "test_query_schedule.mp3",
            "description": "Chinese query about schedule"
        },
        {
            "text": "What is the weather forecast for tomorrow?",
            "voice": "en-US-AriaNeural",
            "filename": "test_weather_query.mp3",
            "description": "English weather query"
        },
        {
            "text": "谢谢你的帮助。",
            "voice": "zh-CN-XiaoxiaoNeural",
            "filename": "test_thank_you.mp3",
            "description": "Chinese thank you"
        }
    ]

    print("🎤 Generating test audio files with Edge TTS...\n")

    for test_case in test_cases:
        print(f"Generating: {test_case['filename']}")
        print(f"  Text: {test_case['text']}")
        print(f"  Voice: {test_case['voice']}")
        print(f"  Description: {test_case['description']}")

        # Create TTS provider
        config = TTSConfig(
            voice=test_case['voice'],
            rate="+0%"
        )
        tts = get_tts_provider("edge-tts", config)

        # Generate audio
        try:
            audio_data = await tts.synthesize_full(test_case['text'])

            # Save to file
            output_path = fixtures_dir / test_case['filename']
            with open(output_path, 'wb') as f:
                f.write(audio_data)

            print(f"  ✅ Saved: {output_path} ({len(audio_data)} bytes)\n")

        except Exception as e:
            print(f"  ❌ Error: {e}\n")
            continue

    # Generate metadata file
    metadata = {
        "generated_at": "2025-01-04",
        "tts_provider": "edge-tts",
        "test_cases": [
            {
                "filename": tc["filename"],
                "text": tc["text"],
                "voice": tc["voice"],
                "description": tc["description"]
            }
            for tc in test_cases
        ]
    }

    import json
    metadata_path = fixtures_dir / "audio_metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"✅ Metadata saved: {metadata_path}")
    print(f"\n🎉 Generated {len(test_cases)} test audio files in {fixtures_dir}")


if __name__ == "__main__":
    asyncio.run(generate_test_audio())
