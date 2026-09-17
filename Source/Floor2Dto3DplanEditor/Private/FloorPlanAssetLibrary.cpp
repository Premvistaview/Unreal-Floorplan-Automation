// Copyright Epic Games, Inc. All Rights Reserved.

#include "FloorPlanAssetLibrary.h"

#include "AssetToolsModule.h"
#include "Components/DynamicMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "DynamicMesh/DynamicMesh3.h"
#include "Engine/Blueprint.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GeometryScript/CollisionFunctions.h"
#include "GeometryScript/CreateNewAssetUtilityFunctions.h"
#include "GeometryScript/GeometryScriptSelectionTypes.h"
#include "GeometryScript/MeshBasicEditFunctions.h"
#include "GeometryScript/MeshUVFunctions.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "ObjectTools.h"
#include "PhysicsEngine/BodySetup.h"
#include "Subsystems/EditorAssetSubsystem.h"
#include "UDynamicMesh.h"
#include "WallGenerator.h"

DEFINE_LOG_CATEGORY_STATIC(LogFloorPlanAssets, Log, All);

namespace
{
	FString NormalizeGameFolder(FString Folder)
	{
		Folder.TrimStartAndEndInline();
		Folder.ReplaceInline(TEXT("\\"), TEXT("/"));
		if (Folder.IsEmpty())
		{
			Folder = TEXT("/Game/Generated/FloorPlans");
		}
		if (!Folder.StartsWith(TEXT("/Game")))
		{
			Folder = TEXT("/Game/") + Folder.TrimChar(TEXT('/'));
		}
		Folder.RemoveFromEnd(TEXT("/"));
		return Folder;
	}

	FString MakeUniqueAssetPath(const FString& BasePackagePath)
	{
		FString UniquePackageName;
		FString UniqueAssetName;
		FAssetToolsModule::GetModule().Get().CreateUniqueAssetName(
			BasePackagePath,
			FString(),
			UniquePackageName,
			UniqueAssetName);
		return UniquePackageName;
	}
}

UBlueprint* UFloorPlanAssetLibrary::FinalizeWallGeneratorAsBlueprint(
	AWallGeneratorActor* WallGenerator,
	const FString& OutputFolder,
	const FString& BaseName,
	const bool bGenerateCollision)
{
	if (!IsValid(WallGenerator) || !IsValid(WallGenerator->DynamicMeshComponent))
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Cannot finalize walls: the WallGeneratorActor is invalid."));
		return nullptr;
	}

	UDynamicMesh* DynamicMesh = WallGenerator->DynamicMeshComponent->GetDynamicMesh();
	if (!IsValid(DynamicMesh) || DynamicMesh->GetTriangleCount() == 0)
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Cannot finalize walls: the generated Dynamic Mesh is empty."));
		return nullptr;
	}

	const FString Folder = NormalizeGameFolder(OutputFolder);
	FString CleanBaseName = ObjectTools::SanitizeObjectName(BaseName);
	if (CleanBaseName.IsEmpty())
	{
		CleanBaseName = TEXT("FloorPlan");
	}

	const FString StaticMeshPath = MakeUniqueAssetPath(
		FString::Printf(TEXT("%s/SM_%s"), *Folder, *CleanBaseName));

	FGeometryScriptCreateNewStaticMeshAssetOptions MeshOptions;
	MeshOptions.bEnableRecomputeNormals = true;
	MeshOptions.bEnableRecomputeTangents = true;
	MeshOptions.bEnableCollision = bGenerateCollision;
	MeshOptions.CollisionMode = bGenerateCollision
		? ECollisionTraceFlag::CTF_UseComplexAsSimple
		: ECollisionTraceFlag::CTF_UseDefault;

	EGeometryScriptOutcomePins MeshOutcome = EGeometryScriptOutcomePins::Failure;
	UStaticMesh* StaticMesh =
		UGeometryScriptLibrary_CreateNewAssetFunctions::CreateNewStaticMeshAssetFromMesh(
			DynamicMesh,
			StaticMeshPath,
			MeshOptions,
			MeshOutcome);

	if (!IsValid(StaticMesh) || MeshOutcome != EGeometryScriptOutcomePins::Success)
	{
		UE_LOG(
			LogFloorPlanAssets,
			Error,
			TEXT("Failed to create Static Mesh asset at %s."),
			*StaticMeshPath);
		return nullptr;
	}

	UWorld* World = WallGenerator->GetWorld();
	if (!IsValid(World))
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Static Mesh was created, but the editor world is unavailable."));
		return nullptr;
	}

	FActorSpawnParameters SpawnParameters;
	SpawnParameters.Name = MakeUniqueObjectName(World, AStaticMeshActor::StaticClass(), *CleanBaseName);
	SpawnParameters.ObjectFlags |= RF_Transactional;

	AStaticMeshActor* StaticMeshActor = World->SpawnActor<AStaticMeshActor>(
		AStaticMeshActor::StaticClass(),
		WallGenerator->GetActorTransform(),
		SpawnParameters);
	if (!IsValid(StaticMeshActor))
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Static Mesh was created, but its temporary actor could not be spawned."));
		return nullptr;
	}

	StaticMeshActor->SetActorLabel(CleanBaseName);
	UStaticMeshComponent* StaticMeshComponent = StaticMeshActor->GetStaticMeshComponent();
	StaticMeshComponent->SetMobility(EComponentMobility::Static);
	StaticMeshComponent->SetStaticMesh(StaticMesh);
	StaticMeshComponent->SetCollisionEnabled(
		bGenerateCollision ? ECollisionEnabled::QueryAndPhysics : ECollisionEnabled::NoCollision);

	const FString BlueprintPath = MakeUniqueAssetPath(
		FString::Printf(TEXT("%s/BP_%s"), *Folder, *CleanBaseName));

	FKismetEditorUtilities::FCreateBlueprintFromActorParams BlueprintParams;
	BlueprintParams.bReplaceActor = true;
	BlueprintParams.bKeepMobility = true;
	BlueprintParams.bOpenBlueprint = false;

	UBlueprint* Blueprint = FKismetEditorUtilities::CreateBlueprintFromActor(
		BlueprintPath,
		StaticMeshActor,
		BlueprintParams);
	if (!IsValid(Blueprint))
	{
		World->DestroyActor(StaticMeshActor);
		UE_LOG(
			LogFloorPlanAssets,
			Error,
			TEXT("Static Mesh was created, but Blueprint creation failed at %s."),
			*BlueprintPath);
		return nullptr;
	}

	WallGenerator->Destroy();

	if (GEditor)
	{
		if (UEditorAssetSubsystem* AssetSubsystem = GEditor->GetEditorSubsystem<UEditorAssetSubsystem>())
		{
			AssetSubsystem->SaveLoadedAsset(StaticMesh, false);
			AssetSubsystem->SaveLoadedAsset(Blueprint, false);
		}
	}

	UE_LOG(
		LogFloorPlanAssets,
		Log,
		TEXT("Final output created: %s containing Static Mesh %s."),
		*Blueprint->GetPathName(),
		*StaticMesh->GetPathName());

	return Blueprint;
}

AStaticMeshActor* UFloorPlanAssetLibrary::BakeWallsToStaticMesh(
	const TArray<AActor*>& WallActors,
	const FString& OutputFolder,
	const FString& BaseName,
	const bool bGenerateCollision,
	const bool bRemoveSourceActors,
	const bool bEnableNanite,
	FString& OutStaticMeshPath)
{
	OutStaticMeshPath.Reset();

	TArray<AActor*> Sources;
	for (AActor* Actor : WallActors)
	{
		if (IsValid(Actor))
		{
			Sources.Add(Actor);
		}
	}
	if (Sources.IsEmpty())
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Bake: no wall actors were given."));
		return nullptr;
	}

	UWorld* World = Sources[0]->GetWorld();
	if (!IsValid(World))
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Bake: the wall actors have no world."));
		return nullptr;
	}

	UE_LOG(LogFloorPlanAssets, Log, TEXT("Baking corrected walls to Static Mesh..."));

	// Combined mode: one generator holds everything, so bake in its local
	// space and place the result at its transform. Anything else is merged
	// in world space and placed at the origin.
	AWallGeneratorActor* SingleGenerator = Sources.Num() == 1 ? Cast<AWallGeneratorActor>(Sources[0]) : nullptr;
	const FTransform Placement = SingleGenerator ? SingleGenerator->GetActorTransform() : FTransform::Identity;

	UDynamicMesh* Merged = NewObject<UDynamicMesh>(GetTransientPackage());
	Merged->Reset();
	int32 Appended = 0;
	for (AActor* Source : Sources)
	{
		UDynamicMeshComponent* Component = Source->FindComponentByClass<UDynamicMeshComponent>();
		UDynamicMesh* SourceMesh = Component ? Component->GetDynamicMesh() : nullptr;
		if (!IsValid(SourceMesh) || SourceMesh->GetTriangleCount() == 0)
		{
			UE_LOG(LogFloorPlanAssets, Warning, TEXT("Bake: %s has no mesh and was skipped."), *Source->GetActorLabel());
			continue;
		}
		const FTransform AppendTransform = SingleGenerator ? FTransform::Identity : Component->GetComponentTransform();
		UGeometryScriptLibrary_MeshBasicEditFunctions::AppendMesh(Merged, SourceMesh, AppendTransform, /*bDeferChangeNotifications*/ true);
		++Appended;
	}

	if (Merged->GetTriangleCount() == 0)
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Bake: the merged wall mesh is empty; nothing to bake."));
		return nullptr;
	}
	if (SingleGenerator)
	{
		UE_LOG(LogFloorPlanAssets, Log, TEXT("Using the combined actor's mesh: %d wall(s), %d triangles."),
			SingleGenerator->GeneratedWallCount, Merged->GetTriangleCount());
	}
	else
	{
		UE_LOG(LogFloorPlanAssets, Log, TEXT("Merged %d wall actor(s) into one mesh (%d triangles)."),
			Appended, Merged->GetTriangleCount());
	}

	// UV0: box projection sized to the mesh, so every wall face gets a sane
	// material mapping. UV1: XAtlas atlas for lightmaps (non-overlapping charts).
	{
		const UE::Geometry::FAxisAlignedBox3d Bounds = Merged->GetMeshRef().GetBounds();
		const FVector Extent = FVector(Bounds.Extents()).ComponentMax(FVector(1.0, 1.0, 1.0));
		const FTransform BoxTransform(FQuat::Identity, FVector(Bounds.Center()), Extent);
		FGeometryScriptMeshSelection WholeMesh;   // empty selection = every triangle

		UGeometryScriptLibrary_MeshUVFunctions::SetNumUVSets(Merged, 2);
		UGeometryScriptLibrary_MeshUVFunctions::SetMeshUVsFromBoxProjection(Merged, 0, BoxTransform, WholeMesh, /*MinIslandTriCount*/ 2);
		FGeometryScriptXAtlasOptions AtlasOptions;
		UGeometryScriptLibrary_MeshUVFunctions::AutoGenerateXAtlasMeshUVs(Merged, 1, AtlasOptions);
		UE_LOG(LogFloorPlanAssets, Log, TEXT("Generated UV0 (box projection) and lightmap UV1 (XAtlas)."));
	}

	// Create the asset.
	const FString Folder = NormalizeGameFolder(OutputFolder);
	FString CleanBaseName = ObjectTools::SanitizeObjectName(BaseName);
	if (CleanBaseName.IsEmpty())
	{
		CleanBaseName = TEXT("FloorPlanWalls");
	}
	const FString StaticMeshPath = MakeUniqueAssetPath(FString::Printf(TEXT("%s/SM_%s"), *Folder, *CleanBaseName));

	FGeometryScriptCreateNewStaticMeshAssetOptions MeshOptions;
	MeshOptions.bEnableRecomputeNormals = true;
	MeshOptions.bEnableRecomputeTangents = true;
	MeshOptions.bEnableNanite = bEnableNanite;
	MeshOptions.bEnableCollision = bGenerateCollision;
	// Simple primitives are added below; the trace flag is finalised after we know whether any were produced.
	MeshOptions.CollisionMode = ECollisionTraceFlag::CTF_UseDefault;

	EGeometryScriptOutcomePins Outcome = EGeometryScriptOutcomePins::Failure;
	UStaticMesh* StaticMesh = UGeometryScriptLibrary_CreateNewAssetFunctions::CreateNewStaticMeshAssetFromMesh(
		Merged, StaticMeshPath, MeshOptions, Outcome);
	if (!IsValid(StaticMesh) || Outcome != EGeometryScriptOutcomePins::Success)
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Bake: failed to create the Static Mesh asset at %s."), *StaticMeshPath);
		return nullptr;
	}
	UE_LOG(LogFloorPlanAssets, Log, TEXT("Static Mesh asset created: %s"), *StaticMesh->GetPathName());

	// Lightmap channel: use the XAtlas UV1 and let the mesh build keep it in sync.
	if (StaticMesh->GetNumSourceModels() > 0)
	{
		FStaticMeshSourceModel& SourceModel = StaticMesh->GetSourceModel(0);
		SourceModel.BuildSettings.bGenerateLightmapUVs = true;
		SourceModel.BuildSettings.SrcLightmapIndex = 0;
		SourceModel.BuildSettings.DstLightmapIndex = 1;
		SourceModel.BuildSettings.MinLightmapResolution = 64;
	}
	StaticMesh->SetLightMapCoordinateIndex(1);
	StaticMesh->SetLightMapResolution(128);

	// Collision: one oriented box per wall (each wall is its own connected
	// component), which is far cheaper than complex-as-simple at runtime.
	if (bGenerateCollision)
	{
		FGeometryScriptCollisionFromMeshOptions CollisionOptions;
		CollisionOptions.bEmitTransaction = false;
		CollisionOptions.Method = EGeometryScriptCollisionGenerationMethod::OrientedBoxes;
		UGeometryScriptLibrary_CollisionFunctions::SetStaticMeshCollisionFromMesh(Merged, StaticMesh, CollisionOptions);

		UBodySetup* BodySetup = StaticMesh->GetBodySetup();
		const int32 SimpleShapes = BodySetup ? BodySetup->AggGeom.GetElementCount() : 0;
		if (BodySetup)
		{
			BodySetup->CollisionTraceFlag = SimpleShapes > 0
				? ECollisionTraceFlag::CTF_UseDefault
				: ECollisionTraceFlag::CTF_UseComplexAsSimple;
			BodySetup->InvalidatePhysicsData();
			BodySetup->CreatePhysicsMeshes();
		}
		if (SimpleShapes > 0)
		{
			UE_LOG(LogFloorPlanAssets, Log, TEXT("Collision generated on Static Mesh: %d oriented box(es)."), SimpleShapes);
		}
		else
		{
			UE_LOG(LogFloorPlanAssets, Warning, TEXT("Collision generated on Static Mesh: no simple shapes produced; using complex-as-simple."));
		}
	}

	StaticMesh->Build(/*bInSilent*/ true);
	StaticMesh->PostEditChange();
	StaticMesh->MarkPackageDirty();
	UE_LOG(LogFloorPlanAssets, Log, TEXT("Static Mesh built with %d UV channel(s); lightmap channel %d."),
		StaticMesh->GetNumUVChannels(0), StaticMesh->GetLightMapCoordinateIndex());

	// Place the result.
	FActorSpawnParameters SpawnParameters;
	SpawnParameters.Name = MakeUniqueObjectName(World, AStaticMeshActor::StaticClass(), *FString::Printf(TEXT("%s_Baked"), *CleanBaseName));
	SpawnParameters.ObjectFlags |= RF_Transactional;
	AStaticMeshActor* BakedActor = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), Placement, SpawnParameters);
	if (!IsValid(BakedActor))
	{
		UE_LOG(LogFloorPlanAssets, Error, TEXT("Bake: the Static Mesh asset was created but its actor could not be spawned."));
		OutStaticMeshPath = StaticMesh->GetPathName();
		return nullptr;
	}

	BakedActor->SetActorLabel(FString::Printf(TEXT("%s_Baked"), *CleanBaseName));
	BakedActor->SetFolderPath(TEXT("FloorPlan_Walls"));
	BakedActor->Tags.AddUnique(TEXT("FloorPlanBakedWalls"));
	if (UStaticMeshComponent* MeshComponent = BakedActor->GetStaticMeshComponent())
	{
		MeshComponent->SetMobility(EComponentMobility::Static);
		MeshComponent->SetStaticMesh(StaticMesh);
		MeshComponent->SetCollisionEnabled(bGenerateCollision ? ECollisionEnabled::QueryAndPhysics : ECollisionEnabled::NoCollision);
	}

	// The Dynamic Mesh actors were only ever the correction surface.
	int32 Removed = 0;
	if (bRemoveSourceActors)
	{
		for (AActor* Source : Sources)
		{
			if (IsValid(Source) && World->DestroyActor(Source))
			{
				++Removed;
			}
		}
	}

	if (GEditor)
	{
		if (UEditorAssetSubsystem* AssetSubsystem = GEditor->GetEditorSubsystem<UEditorAssetSubsystem>())
		{
			AssetSubsystem->SaveLoadedAsset(StaticMesh, false);
		}
	}

	OutStaticMeshPath = StaticMesh->GetPathName();
	UE_LOG(LogFloorPlanAssets, Log, TEXT("Finalized: Static Mesh Actor '%s' placed, %d Dynamic Mesh actor(s) removed."),
		*BakedActor->GetActorLabel(), Removed);
	return BakedActor;
}
