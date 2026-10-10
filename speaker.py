
import torch
import sounddevice as sd
from qwen_tts import Qwen3TTSModel

# Load the model once
device = "cuda:0" if torch.cuda.is_available() else "cpu"

model = Qwen3TTSModel.from_pretrained(
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    device_map=device,
    dtype=torch.float16 if device == "cuda:0" else torch.float32,
)

def speak(text):
    # Generate speech in memory
    audio, sample_rate = model.generate_custom_voice(
        text=text,
        language="English",
        speaker="Ryan",
    )

    # Play directly without saving an audio file
    sd.play(audio[0], samplerate=sample_rate)
    sd.wait()


if __name__ == "__main__":
    while True:
        text = input("Enter text (or 'exit' to quit): ")

        if text.lower() == "exit":
            break

        if text.strip():
            speak(text)