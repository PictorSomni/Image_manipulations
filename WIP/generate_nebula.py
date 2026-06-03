import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import random

def generate_fbm_noise(width, height, octaves=7, persistence=0.55):
    noise = np.zeros((height, width))
    amplitude = 1.0
    total_amp = 0.0
    
    for i in range(octaves):
        res_x = 4 * (2**i)
        res_y = int(res_x * (height / width))
        if res_y < 4: res_y = 4
        
        grid = np.random.rand(res_y, res_x)
        img_grid = Image.fromarray((grid * 255).astype(np.uint8))
        img_upscaled = img_grid.resize((width, height), resample=Image.Resampling.BICUBIC)
        noise_octave = np.array(img_upscaled).astype(np.float32) / 255.0
        
        noise += noise_octave * amplitude
        total_amp += amplitude
        amplitude *= persistence
        
    return noise / total_amp

def create_nebula(width=1200, height=800, filename="nebula_saturee_contrastee.png"):
    density_noise = generate_fbm_noise(width, height, octaves=7, persistence=0.55)
    color_noise_1 = generate_fbm_noise(width, height, octaves=5, persistence=0.5)
    color_noise_2 = generate_fbm_noise(width, height, octaves=5, persistence=0.5)
    
    # Contraste de la densité (espace sombre profond vs nuages denses)
    density = np.clip(density_noise, 0, 1)
    density = np.power(density, 2.5)
    density = (density - 0.08) / 0.85
    density = np.clip(density, 0, 1)
    
    # Couleurs de base
    bg = np.array([0.01, 0.005, 0.025]) # Fond violet ultra sombre
    color1 = np.array([0.95, 0.05, 0.65]) # Magenta saturé
    color2 = np.array([0.0, 0.55, 1.0])  # Cyan électrique
    color3 = np.array([1.0, 0.7, 0.25])  # Or / Orange chaud pour les cœurs de pouponnières d'étoiles
    
    density_3d = np.expand_dims(density, axis=2)
    color_noise_1_3d = np.expand_dims(color_noise_1, axis=2)
    color_noise_2_3d = np.expand_dims(color_noise_2, axis=2)
    
    # Mélange des couleurs de gaz
    gas_color = color1 * (1.0 - color_noise_1_3d) + color2 * color_noise_1_3d
    
    # Ajout des zones d'or chaud dans les parties les plus denses
    highlight_mask = np.clip((density_3d - 0.35) / 0.65, 0, 1) * color_noise_2_3d
    gas_color = gas_color * (1.0 - highlight_mask) + color3 * highlight_mask
    
    # Application de la densité et fusion avec le fond
    nebula_rgb = gas_color * density_3d
    final_rgb = bg * (1.0 - density_3d) + nebula_rgb
    
    # Boost léger de luminosité globale
    final_rgb = np.clip(final_rgb * 1.15, 0, 1)
    
    # Conversion PIL
    img_array = (final_rgb * 255).astype(np.uint8)
    nebula_img = Image.fromarray(img_array)
    
    # Génération des étoiles
    stars_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(stars_layer)
    
    # 1. Étoiles lointaines d'arrière-plan
    num_background_stars = 1200
    for _ in range(num_background_stars):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        brightness = int(random.uniform(60, 210))
        tint = random.choice([
            (brightness, brightness, brightness),
            (int(brightness*0.8), int(brightness*0.8), brightness),
            (brightness, int(brightness*0.8), int(brightness*0.8))
        ])
        draw.point((x, y), fill=tint + (brightness,))
        
    # 2. Étoiles moyennes avec un halo doux
    num_medium_stars = 60
    for _ in range(num_medium_stars):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        r = random.uniform(1.0, 2.2)
        brightness = int(random.uniform(160, 255))
        draw.ellipse([x-r*2, y-r*2, x+r*2, y+r*2], fill=(255, 255, 255, int(brightness*0.25)))
        draw.ellipse([x-r, y-r, x+r, y+r], fill=(255, 255, 255, brightness))
        
    # 3. Étoiles brillantes avec aigrettes de diffraction (style JWST)
    num_bright_stars = 7
    for _ in range(num_bright_stars):
        x = random.randint(100, width - 100)
        y = random.randint(100, height - 100)
        r = random.uniform(2.5, 4.0)
        
        # Cœur brillant
        draw.ellipse([x-r, y-r, x+r, y+r], fill=(255, 255, 255, 255))
        draw.ellipse([x-r*2.5, y-r*2.5, x+r*2.5, y+r*2.5], fill=(255, 255, 255, 70))
        
        # Aigrettes de diffraction
        spike_len = random.uniform(15, 32)
        draw.line([x - spike_len, y, x + spike_len, y], fill=(255, 255, 255, 160), width=1)
        draw.line([x, y - spike_len, x, y + spike_len], fill=(255, 255, 255, 160), width=1)
        diag_len = spike_len * 0.7
        draw.line([x - diag_len, y - diag_len, x + diag_len, y + diag_len], fill=(255, 255, 255, 90), width=1)
        draw.line([x - diag_len, y + diag_len, x + diag_len, y - diag_len], fill=(255, 255, 255, 90), width=1)

    # Flou gaussien léger sur les étoiles pour un effet de diffusion réaliste
    stars_blurred = stars_layer.filter(ImageFilter.GaussianBlur(0.5))
    nebula_img.paste(stars_blurred, (0, 0), stars_blurred)
    
    # Sauvegarde
    nebula_img.save(filename)
    print(f"Superbe nébuleuse générée avec succès : {filename}")

if __name__ == "__main__":
    create_nebula()
